use num_complex::Complex64;
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray2, PyReadonlyArray3};
use pyo3::prelude::*;
use rayon::prelude::*;

/// Apply shunt termination to port `port_k` of an N-port S-matrix for all frequencies.
///
/// Formula (rank-1 update):
///   S'[i,j] = S[i,j] + S[i,k] * Γ * S[k,j] / (1 - S[k,k] * Γ)
///   where i,j run over all ports EXCEPT k, with index remapping i -> i+(i>=k).
///
/// # Arguments
/// * `s`      - flat (nfreq * n * n) complex array, row-major
/// * `n`      - current number of ports
/// * `nfreq`  - number of frequency points
/// * `port_k` - 0-based port index to terminate (always 2 in our scheme)
/// * `gamma`  - slice of length nfreq, reflection coefficient per frequency
///
/// # Returns
/// Flat (nfreq * (n-1) * (n-1)) complex array
fn apply_termination(
    s: &[Complex64],
    n: usize,
    nfreq: usize,
    port_k: usize,
    gamma: &[Complex64],
) -> Vec<Complex64> {
    let n1 = n - 1;
    let mut result = vec![Complex64::new(0.0, 0.0); nfreq * n1 * n1];

    for f in 0..nfreq {
        let s_kk = s[f * n * n + port_k * n + port_k];
        let g = gamma[f];
        let denom = Complex64::new(1.0, 0.0) - s_kk * g;

        for i in 0..n1 {
            let ii = if i >= port_k { i + 1 } else { i };
            for j in 0..n1 {
                let jj = if j >= port_k { j + 1 } else { j };
                let s_ij  = s[f * n * n + ii * n + jj];
                let s_ik  = s[f * n * n + ii * n + port_k];
                let s_kj  = s[f * n * n + port_k * n + jj];
                result[f * n1 * n1 + i * n1 + j] = s_ij + s_ik * g * s_kj / denom;
            }
        }
    }
    result
}

/// Evaluate 2-port metrics from a flat (nfreq * 2 * 2) complex S-matrix.
/// Returns (vswr_s11_max, vswr_s22_max, worst_il_db) over the eval freq range.
fn compute_metrics(
    s2: &[Complex64],
    nfreq: usize,
    eval_start: usize,
    eval_stop: usize,
) -> (f64, f64, f64) {
    let mut vswr_s11_max = 1.0_f64;
    let mut vswr_s22_max = 1.0_f64;
    let mut worst_il_db = 0.0_f64;

    for f in eval_start..=eval_stop.min(nfreq - 1) {
        // 2x2 layout: [s11, s12, s21, s22]
        let s11_mag = s2[f * 4].norm().min(0.99999);
        let s22_mag = s2[f * 4 + 3].norm().min(0.99999);
        let s21_mag = s2[f * 4 + 2].norm().max(1e-15_f64);

        let vswr11 = (1.0 + s11_mag) / (1.0 - s11_mag);
        let vswr22 = (1.0 + s22_mag) / (1.0 - s22_mag);
        let il_db  = 20.0 * s21_mag.log10();

        if vswr11 > vswr_s11_max { vswr_s11_max = vswr11; }
        if vswr22 > vswr_s22_max { vswr_s22_max = vswr22; }
        if il_db  < worst_il_db  { worst_il_db  = il_db; }
    }
    (vswr_s11_max, vswr_s22_max, worst_il_db)
}

/// Build all combination index arrays for n_ports ports with counts[i] candidates each.
fn build_combos(counts: &[usize]) -> Vec<Vec<usize>> {
    let total: usize = counts.iter().product();
    let mut combos = Vec::with_capacity(total);
    let mut combo = vec![0usize; counts.len()];
    for _ in 0..total {
        combos.push(combo.clone());
        // Increment last index, carry over
        for p in (0..counts.len()).rev() {
            combo[p] += 1;
            if combo[p] < counts[p] {
                break;
            }
            combo[p] = 0;
        }
    }
    combos
}

/// Main sweep function exposed to Python.
///
/// # Arguments
/// * `base_s_re` / `base_s_im`  - (nfreq, N, N) float64 base S-matrix (re/im split)
/// * `term_gammas_re` / `_im`   - list of (n_cands, nfreq) float64 per tunable port.
///                                Row 0 = open (Γ=+1 re=1, im=0).
///                                Rows 1..n_cands = actual component gammas.
/// * `eval_start_idx`            - first frequency index included in metric evaluation
/// * `eval_stop_idx`             - last frequency index (inclusive) in metric evaluation
///
/// # Returns
/// Tuple of four numpy arrays:
/// * vswr_s11_max  : (n_combos,) float64
/// * vswr_s22_max  : (n_combos,) float64
/// * worst_il_db   : (n_combos,) float64
/// * combo_indices : (n_combos, n_ports) int32  — which candidate row was used per port
#[pyfunction]
fn sweep_terminations_parallel<'py>(
    py: Python<'py>,
    base_s_re: PyReadonlyArray3<'py, f64>,
    base_s_im: PyReadonlyArray3<'py, f64>,
    term_gammas_re: Vec<PyReadonlyArray2<'py, f64>>,
    term_gammas_im: Vec<PyReadonlyArray2<'py, f64>>,
    eval_start_idx: usize,
    eval_stop_idx: usize,
) -> PyResult<(
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray2<i32>>,
)> {
    let base_re = base_s_re.as_array();
    let base_im = base_s_im.as_array();

    let shape = base_re.shape();
    let nfreq = shape[0];
    let n_ports = shape[1]; // N (includes s1, s2, and all tunable ports)

    let n_tunable = term_gammas_re.len();
    assert_eq!(n_tunable, n_ports - 2, "Expected N-2 tunable ports");

    // Convert base S-matrix to flat Vec<Complex64>
    let base_s: Vec<Complex64> = (0..nfreq)
        .flat_map(|f| {
            (0..n_ports).flat_map(move |i| {
                (0..n_ports).map(move |j| {
                    Complex64::new(base_re[[f, i, j]], base_im[[f, i, j]])
                })
            })
        })
        .collect();

    // Convert termination gammas to Vec<Vec<Vec<Complex64>>>
    // Layout per port: [n_cands][nfreq]
    let mut all_gammas: Vec<Vec<Vec<Complex64>>> = Vec::with_capacity(n_tunable);
    let mut counts: Vec<usize> = Vec::with_capacity(n_tunable);

    for p in 0..n_tunable {
        let gre = term_gammas_re[p].as_array();
        let gim = term_gammas_im[p].as_array();
        let n_cands = gre.shape()[0];
        counts.push(n_cands);

        let mut port_gammas: Vec<Vec<Complex64>> = Vec::with_capacity(n_cands);
        for c in 0..n_cands {
            let gamma: Vec<Complex64> = (0..nfreq)
                .map(|f| Complex64::new(gre[[c, f]], gim[[c, f]]))
                .collect();
            port_gammas.push(gamma);
        }
        all_gammas.push(port_gammas);
    }

    // Build all combination indices
    let combos = build_combos(&counts);
    let n_combos = combos.len();

    // Parallel sweep using rayon
    let results: Vec<(f64, f64, f64)> = combos
        .par_iter()
        .map(|combo_indices| {
            let mut s = base_s.clone();
            let mut current_n = n_ports;

            // Always terminate port 2 (first tunable port) at each step.
            // Port ordering: [s1=0, s2=1, t0=2, t1=3, ...] → after terminating
            // t0 (port 2): [s1=0, s2=1, t1=2, ...] → terminate t1 (now port 2) → ...
            for (p, &cand_idx) in combo_indices.iter().enumerate() {
                let gamma = &all_gammas[p][cand_idx];
                s = apply_termination(&s, current_n, nfreq, 2, gamma);
                current_n -= 1;
            }

            // s is now (nfreq * 2 * 2)
            compute_metrics(&s, nfreq, eval_start_idx, eval_stop_idx)
        })
        .collect();

    // Unpack results into separate arrays
    let mut vswr_s11 = Vec::with_capacity(n_combos);
    let mut vswr_s22 = Vec::with_capacity(n_combos);
    let mut worst_il = Vec::with_capacity(n_combos);
    let mut combo_idx_flat: Vec<i32> = Vec::with_capacity(n_combos * n_tunable);

    for (i, (v11, v22, il)) in results.iter().enumerate() {
        vswr_s11.push(*v11);
        vswr_s22.push(*v22);
        worst_il.push(*il);
        for &ci in &combos[i] {
            combo_idx_flat.push(ci as i32);
        }
    }

    let vswr_s11_arr = PyArray1::from_vec_bound(py, vswr_s11);
    let vswr_s22_arr = PyArray1::from_vec_bound(py, vswr_s22);
    let worst_il_arr = PyArray1::from_vec_bound(py, worst_il);

    use numpy::ndarray::Array2;
    let arr2 = Array2::from_shape_vec(
        (n_combos, n_tunable),
        combo_idx_flat,
    ).unwrap();
    let combo_idx_arr = arr2.into_pyarray_bound(py);

    Ok((vswr_s11_arr, vswr_s22_arr, worst_il_arr, combo_idx_arr))
}

#[pymodule]
fn rf_sweep(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sweep_terminations_parallel, m)?)?;
    Ok(())
}
