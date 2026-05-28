from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import numpy as np
import skrf as rf


PARAMETER_INDEXES: dict[str, tuple[int, int]] = {
    "S11": (0, 0),
    "S21": (1, 0),
    "S12": (0, 1),
    "S22": (1, 1),
}

RETURN_LOSS_PARAMETERS = {"S11", "S22"}

SUMMARY_HEADERS = [
    "File",
    "Parameter",
    "Min Magnitude (dB)",
    "Max Magnitude (dB)",
    "Min Return Loss (dB)",
    "Max Return Loss (dB)",
    "Min VSWR",
    "Max VSWR",
]

DIFFERENCE_HEADERS = [
    "Baseline",
    "Compared",
    "Parameter",
    "Max |Delta| (dB)",
    "Mean |Delta| (dB)",
    "Freq At Max Delta (GHz)",
]


@dataclass(slots=True)
class LoadedNetwork:
    path: Path
    display_name: str
    network: rf.Network
    freq_ghz: np.ndarray
    min_freq_ghz: float
    max_freq_ghz: float

    @classmethod
    def from_path(cls, path: str | Path, display_name: str | None = None) -> "LoadedNetwork":
        resolved_path = Path(path).expanduser().resolve()

        try:
            network = rf.Network(str(resolved_path))
        except Exception as exc:  # pragma: no cover - exercised via UI validation
            raise ValueError(f"Could not load Touchstone data: {exc}") from exc

        if network.nports != 2:
            raise ValueError(
                f"Only 2-port Touchstone files are supported, but {resolved_path.name} "
                f"contains {network.nports} ports."
            )

        freq_ghz = np.asarray(network.f, dtype=float) / 1e9
        if freq_ghz.size < 2:
            raise ValueError(
                "The file does not contain enough frequency samples to compare.")

        return cls(
            path=resolved_path,
            display_name=display_name or resolved_path.name,
            network=network,
            freq_ghz=freq_ghz,
            min_freq_ghz=float(freq_ghz[0]),
            max_freq_ghz=float(freq_ghz[-1]),
        )


@dataclass(slots=True)
class SummaryRow:
    file_name: str
    parameter: str
    min_db: float
    max_db: float
    min_return_loss_db: float | None
    max_return_loss_db: float | None
    min_vswr: float | None
    max_vswr: float | None


@dataclass(slots=True)
class DeltaRow:
    baseline_file: str
    compared_file: str
    parameter: str
    max_abs_delta_db: float
    mean_abs_delta_db: float
    frequency_at_max_ghz: float


@dataclass(slots=True)
class ComparisonResult:
    file_order: list[str]
    frequency_ghz: np.ndarray
    traces: dict[str, dict[str, np.ndarray]]
    magnitude_db: dict[str, dict[str, np.ndarray]]
    return_loss_db: dict[str, dict[str, np.ndarray]]
    vswr: dict[str, dict[str, np.ndarray]]
    summary_rows: list[SummaryRow]
    delta_rows: list[DeltaRow]
    selected_start_ghz: float
    selected_stop_ghz: float
    common_start_ghz: float
    common_stop_ghz: float
    baseline_file: str


def common_frequency_range(networks: Iterable[LoadedNetwork]) -> tuple[float, float]:
    items = list(networks)
    if not items:
        raise ValueError("Add at least one .s2p file first.")

    start = max(item.min_freq_ghz for item in items)
    stop = min(item.max_freq_ghz for item in items)
    if start >= stop:
        raise ValueError(
            "The selected files do not share a common frequency range.")
    return float(start), float(stop)


def compare_networks(
    networks: Iterable[LoadedNetwork],
    selected_start_ghz: float,
    selected_stop_ghz: float,
) -> ComparisonResult:
    items = list(networks)
    if len(items) < 2:
        raise ValueError("Select at least two valid .s2p files to compare.")

    common_start_ghz, common_stop_ghz = common_frequency_range(items)
    _validate_frequency_range(
        selected_start_ghz,
        selected_stop_ghz,
        common_start_ghz,
        common_stop_ghz,
    )

    target_freq_ghz = _build_frequency_axis(
        items, selected_start_ghz, selected_stop_ghz)
    traces: dict[str, dict[str, np.ndarray]] = {}
    magnitude_db: dict[str, dict[str, np.ndarray]] = {}
    return_loss_db: dict[str, dict[str, np.ndarray]] = {}
    vswr: dict[str, dict[str, np.ndarray]] = {}

    for item in items:
        traces[item.display_name] = {}
        magnitude_db[item.display_name] = {}
        return_loss_db[item.display_name] = {}
        vswr[item.display_name] = {}
        for parameter, (row_idx, col_idx) in PARAMETER_INDEXES.items():
            trace = _interpolate_complex(
                item.freq_ghz,
                np.asarray(item.network.s[:, row_idx,
                           col_idx], dtype=np.complex128),
                target_freq_ghz,
            )
            traces[item.display_name][parameter] = trace
            magnitude = _to_db(trace)
            magnitude_db[item.display_name][parameter] = magnitude
            if parameter in RETURN_LOSS_PARAMETERS:
                return_loss_db[item.display_name][parameter] = -magnitude
                vswr[item.display_name][parameter] = _to_vswr(trace)

    summary_rows = _build_summary_rows(
        items, magnitude_db, return_loss_db, vswr)
    delta_rows = _build_delta_rows(items, target_freq_ghz, magnitude_db)

    return ComparisonResult(
        file_order=[item.display_name for item in items],
        frequency_ghz=target_freq_ghz,
        traces=traces,
        magnitude_db=magnitude_db,
        return_loss_db=return_loss_db,
        vswr=vswr,
        summary_rows=summary_rows,
        delta_rows=delta_rows,
        selected_start_ghz=float(selected_start_ghz),
        selected_stop_ghz=float(selected_stop_ghz),
        common_start_ghz=common_start_ghz,
        common_stop_ghz=common_stop_ghz,
        baseline_file=items[0].display_name,
    )


def build_summary_lines(result: ComparisonResult) -> list[str]:
    lines = [
        "RF KPI Comparison Report",
        "",
        f"Files compared: {', '.join(result.file_order)}",
        (
            "Selected range (GHz): "
            f"{result.selected_start_ghz:.6f} - {result.selected_stop_ghz:.6f}"
        ),
        (
            "Shared range (GHz): "
            f"{result.common_start_ghz:.6f} - {result.common_stop_ghz:.6f}"
        ),
        f"Baseline file: {result.baseline_file}",
        "",
        "Per-file metrics:",
    ]

    for row in result.summary_rows:
        text = (
            f"{row.file_name} {row.parameter}: min {row.min_db:.3f} dB, "
            f"max {row.max_db:.3f} dB"
        )
        if row.min_return_loss_db is not None:
            text += (
                f", RL {row.min_return_loss_db:.3f} to {row.max_return_loss_db:.3f} dB"
                f", VSWR {row.min_vswr:.3f} to {row.max_vswr:.3f}"
            )
        lines.append(text)

    if result.delta_rows:
        lines.extend(["", "Pairwise deltas vs baseline:"])
        for row in result.delta_rows:
            lines.append(
                f"{row.compared_file} {row.parameter}: max |Delta| {row.max_abs_delta_db:.3f} dB "
                f"at {row.frequency_at_max_ghz:.6f} GHz, mean |Delta| {row.mean_abs_delta_db:.3f} dB"
            )

    return lines


def export_excel_report(
    result: ComparisonResult,
    destination: str | Path,
    plot_image: BytesIO | None,
) -> None:
    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover - dependency check in runtime only
        raise RuntimeError(
            "Install xlsxwriter to enable Excel export.") from exc

    workbook = xlsxwriter.Workbook(str(destination))
    title_fmt = workbook.add_format({"bold": True, "font_size": 14})
    header_fmt = workbook.add_format(
        {"bold": True, "bg_color": "#D9E2F3", "border": 1})
    text_fmt = workbook.add_format({"border": 1})
    number_fmt = workbook.add_format({"border": 1, "num_format": "0.000000"})

    try:
        _write_summary_sheet(workbook, result, title_fmt,
                             header_fmt, text_fmt, number_fmt)
        _write_difference_sheet(
            workbook, result, header_fmt, text_fmt, number_fmt)
        _write_trace_sheet(workbook, result, header_fmt, number_fmt)
        _write_plot_sheet(workbook, result, plot_image, title_fmt)
    finally:
        workbook.close()


def _validate_frequency_range(
    selected_start_ghz: float,
    selected_stop_ghz: float,
    common_start_ghz: float,
    common_stop_ghz: float,
) -> None:
    if selected_start_ghz >= selected_stop_ghz:
        raise ValueError(
            "The start frequency must be smaller than the stop frequency.")
    if selected_start_ghz < common_start_ghz or selected_stop_ghz > common_stop_ghz:
        raise ValueError(
            "The selected frequency range must stay within the common range of the loaded files."
        )


def _build_frequency_axis(
    networks: list[LoadedNetwork],
    selected_start_ghz: float,
    selected_stop_ghz: float,
) -> np.ndarray:
    counts = [
        int(
            np.count_nonzero(
                (item.freq_ghz >= selected_start_ghz) & (
                    item.freq_ghz <= selected_stop_ghz)
            )
        )
        for item in networks
    ]
    point_count = min(max(max(counts), 401), 2001)
    return np.linspace(selected_start_ghz, selected_stop_ghz, point_count, dtype=float)


def _interpolate_complex(
    source_freq_ghz: np.ndarray,
    source_values: np.ndarray,
    target_freq_ghz: np.ndarray,
) -> np.ndarray:
    real = np.interp(target_freq_ghz, source_freq_ghz, source_values.real)
    imag = np.interp(target_freq_ghz, source_freq_ghz, source_values.imag)
    return real + 1j * imag


def _to_db(trace: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.clip(np.abs(trace), 1e-15, None))


def _to_vswr(trace: np.ndarray) -> np.ndarray:
    magnitude = np.clip(np.abs(trace), 0.0, 0.999999)
    return (1.0 + magnitude) / (1.0 - magnitude)


def _build_summary_rows(
    networks: list[LoadedNetwork],
    magnitude_db: dict[str, dict[str, np.ndarray]],
    return_loss_db: dict[str, dict[str, np.ndarray]],
    vswr: dict[str, dict[str, np.ndarray]],
) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    for item in networks:
        for parameter in PARAMETER_INDEXES:
            min_return_loss_db: float | None = None
            max_return_loss_db: float | None = None
            min_vswr: float | None = None
            max_vswr: float | None = None
            if parameter in RETURN_LOSS_PARAMETERS:
                return_loss_values = return_loss_db[item.display_name][parameter]
                vswr_values = vswr[item.display_name][parameter]
                min_return_loss_db = float(np.min(return_loss_values))
                max_return_loss_db = float(np.max(return_loss_values))
                min_vswr = float(np.min(vswr_values))
                max_vswr = float(np.max(vswr_values))
            magnitude_values = magnitude_db[item.display_name][parameter]
            rows.append(
                SummaryRow(
                    file_name=item.display_name,
                    parameter=parameter,
                    min_db=float(np.min(magnitude_values)),
                    max_db=float(np.max(magnitude_values)),
                    min_return_loss_db=min_return_loss_db,
                    max_return_loss_db=max_return_loss_db,
                    min_vswr=min_vswr,
                    max_vswr=max_vswr,
                )
            )
    return rows


def _build_delta_rows(
    networks: list[LoadedNetwork],
    frequency_ghz: np.ndarray,
    magnitude_db: dict[str, dict[str, np.ndarray]],
) -> list[DeltaRow]:
    rows: list[DeltaRow] = []
    baseline_file = networks[0].display_name
    for item in networks[1:]:
        for parameter in PARAMETER_INDEXES:
            delta = magnitude_db[item.display_name][parameter] - \
                magnitude_db[baseline_file][parameter]
            abs_delta = np.abs(delta)
            max_index = int(np.argmax(abs_delta))
            rows.append(
                DeltaRow(
                    baseline_file=baseline_file,
                    compared_file=item.display_name,
                    parameter=parameter,
                    max_abs_delta_db=float(abs_delta[max_index]),
                    mean_abs_delta_db=float(np.mean(abs_delta)),
                    frequency_at_max_ghz=float(frequency_ghz[max_index]),
                )
            )
    return rows


def _write_summary_sheet(workbook, result, title_fmt, header_fmt, text_fmt, number_fmt) -> None:
    worksheet = workbook.add_worksheet("Summary")
    worksheet.freeze_panes(7, 0)
    worksheet.set_column(0, 7, 22)
    worksheet.write("A1", "RF KPI Comparison Report", title_fmt)
    worksheet.write("A3", "Compared Files")
    worksheet.write("B3", ", ".join(result.file_order))
    worksheet.write("A4", "Selected Range (GHz)")
    worksheet.write(
        "B4",
        f"{result.selected_start_ghz:.6f} - {result.selected_stop_ghz:.6f}",
    )
    worksheet.write("A5", "Shared Range (GHz)")
    worksheet.write(
        "B5",
        f"{result.common_start_ghz:.6f} - {result.common_stop_ghz:.6f}",
    )
    worksheet.write("A6", "Baseline File")
    worksheet.write("B6", result.baseline_file)

    for column_index, header in enumerate(SUMMARY_HEADERS):
        worksheet.write(6, column_index, header, header_fmt)

    row_index = 7
    for row in result.summary_rows:
        worksheet.write(row_index, 0, row.file_name, text_fmt)
        worksheet.write(row_index, 1, row.parameter, text_fmt)
        worksheet.write_number(row_index, 2, row.min_db, number_fmt)
        worksheet.write_number(row_index, 3, row.max_db, number_fmt)
        _write_optional_number(worksheet, row_index, 4,
                               row.min_return_loss_db, text_fmt, number_fmt)
        _write_optional_number(worksheet, row_index, 5,
                               row.max_return_loss_db, text_fmt, number_fmt)
        _write_optional_number(worksheet, row_index, 6,
                               row.min_vswr, text_fmt, number_fmt)
        _write_optional_number(worksheet, row_index, 7,
                               row.max_vswr, text_fmt, number_fmt)
        row_index += 1


def _write_difference_sheet(workbook, result, header_fmt, text_fmt, number_fmt) -> None:
    worksheet = workbook.add_worksheet("Differences")
    worksheet.freeze_panes(1, 0)
    worksheet.set_column(0, 5, 22)

    for column_index, header in enumerate(DIFFERENCE_HEADERS):
        worksheet.write(0, column_index, header, header_fmt)

    row_index = 1
    for row in result.delta_rows:
        worksheet.write(row_index, 0, row.baseline_file, text_fmt)
        worksheet.write(row_index, 1, row.compared_file, text_fmt)
        worksheet.write(row_index, 2, row.parameter, text_fmt)
        worksheet.write_number(row_index, 3, row.max_abs_delta_db, number_fmt)
        worksheet.write_number(row_index, 4, row.mean_abs_delta_db, number_fmt)
        worksheet.write_number(
            row_index, 5, row.frequency_at_max_ghz, number_fmt)
        row_index += 1


def _write_trace_sheet(workbook, result, header_fmt, number_fmt) -> None:
    worksheet = workbook.add_worksheet("Traces")
    worksheet.freeze_panes(1, 1)
    worksheet.set_column(0, 0, 16)
    worksheet.write(0, 0, "Frequency (GHz)", header_fmt)
    for row_index, frequency in enumerate(result.frequency_ghz, start=1):
        worksheet.write_number(row_index, 0, float(frequency), number_fmt)

    column_index = 1
    for file_name in result.file_order:
        for parameter in PARAMETER_INDEXES:
            worksheet.write(0, column_index,
                            f"{file_name} {parameter} (dB)", header_fmt)
            for row_index, value in enumerate(result.magnitude_db[file_name][parameter], start=1):
                worksheet.write_number(
                    row_index, column_index, float(value), number_fmt)
            column_index += 1


def _write_plot_sheet(workbook, result, plot_image: BytesIO | None, title_fmt) -> None:
    worksheet = workbook.add_worksheet("Plots")
    worksheet.write("A1", "Comparison Plot Overview", title_fmt)
    worksheet.write("A3", "Files")
    worksheet.write("B3", ", ".join(result.file_order))
    worksheet.write("A4", "Selected Range (GHz)")
    worksheet.write(
        "B4",
        f"{result.selected_start_ghz:.6f} - {result.selected_stop_ghz:.6f}",
    )
    worksheet.set_column(0, 1, 24)
    if plot_image is not None:
        plot_image.seek(0)
        worksheet.insert_image(
            "A6",
            "rf_kpi_comparison.png",
            {"image_data": plot_image, "x_scale": 0.9, "y_scale": 0.9},
        )


def _write_optional_number(worksheet, row: int, column: int, value, text_fmt, number_fmt) -> None:
    if value is None:
        worksheet.write(row, column, "N/A", text_fmt)
    else:
        worksheet.write_number(row, column, float(value), number_fmt)
