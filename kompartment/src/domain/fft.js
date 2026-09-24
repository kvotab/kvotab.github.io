/**
 * The discrete Fourier transform, for the spectral sensitivity methods.
 *
 * eFAST, RBD-FAST and EASI read a variance off the power spectrum of the
 * output taken along a curve through the inputs, and the moment-independent
 * δ smooths densities by convolving with a Gaussian in Fourier space. So all
 * of them want `rfft`, and at lengths that are whatever the reader asked for:
 * a thousand, 15,000, 257. A power of two is done radix-2; anything else by
 * Bluestein's algorithm, which is the same transform written as a
 * convolution of power-of-two length -- exact in arithmetic, and good to a
 * few parts in 1e15 in floating point, which is what FFTW gives as well.
 *
 * The convention is FFTW's and AbstractFFTs': the forward transform is
 * unnormalised, `F_k = Σ_n y_n e^{-2πikn/N}`, and `irfft` divides by `N`, so
 * the two are inverses.
 */

/** Whether `n` is a power of two. */
const isPow2 = (n) => n > 0 && (n & (n - 1)) === 0;

/**
 * In place, radix-2, decimation in time. `re` and `im` are one complex vector
 * of power-of-two length; `sign` -1 is the forward transform, +1 the inverse
 * without its 1/N.
 */
function radix2(re, im, sign) {
	const n = re.length;
	for (let i = 1, j = 0; i < n; i++) {
		let bit = n >> 1;
		for (; j & bit; bit >>= 1) j ^= bit;
		j ^= bit;
		if (i < j) {
			let t = re[i]; re[i] = re[j]; re[j] = t;
			t = im[i]; im[i] = im[j]; im[j] = t;
		}
	}
	for (let len = 2; len <= n; len <<= 1) {
		const half = len >> 1;
		// The twiddles from a table computed per stage rather than by
		// repeated multiplication, which would carry its rounding along.
		const step = (sign * 2 * Math.PI) / len;
		for (let k = 0; k < half; k++) {
			const wr = Math.cos(step * k);
			const wi = Math.sin(step * k);
			for (let s = 0; s < n; s += len) {
				const a = s + k;
				const b = a + half;
				const xr = re[b] * wr - im[b] * wi;
				const xi = re[b] * wi + im[b] * wr;
				re[b] = re[a] - xr;
				im[b] = im[a] - xi;
				re[a] += xr;
				im[a] += xi;
			}
		}
	}
}

/**
 * The transform of any length, by Bluestein: `nk = (n² + k² - (k-n)²)/2`
 * turns the sum into a convolution with the chirp `e^{iπn²/N}`, which is done
 * at a power of two at least `2N - 1` long.
 */
function bluestein(re, im, sign) {
	const n = re.length;
	let m = 1;
	while (m < 2 * n - 1) m <<= 1;
	// The chirp's angle from n² mod 2N, so it stays exact for large n where
	// n² itself would lose the low bits that decide it.
	const cr = new Float64Array(n);
	const ci = new Float64Array(n);
	for (let k = 0; k < n; k++) {
		const q = (k * k) % (2 * n);
		const a = (sign * Math.PI * q) / n;
		cr[k] = Math.cos(a);
		ci[k] = Math.sin(a);
	}
	const ar = new Float64Array(m);
	const ai = new Float64Array(m);
	for (let k = 0; k < n; k++) {
		ar[k] = re[k] * cr[k] - im[k] * ci[k];
		ai[k] = re[k] * ci[k] + im[k] * cr[k];
	}
	const br = new Float64Array(m);
	const bi = new Float64Array(m);
	br[0] = cr[0];
	bi[0] = -ci[0];
	for (let k = 1; k < n; k++) {
		br[k] = br[m - k] = cr[k];
		bi[k] = bi[m - k] = -ci[k];
	}
	radix2(ar, ai, -1);
	radix2(br, bi, -1);
	for (let k = 0; k < m; k++) {
		const r = ar[k] * br[k] - ai[k] * bi[k];
		ai[k] = ar[k] * bi[k] + ai[k] * br[k];
		ar[k] = r;
	}
	radix2(ar, ai, 1);
	for (let k = 0; k < n; k++) {
		const r = ar[k] / m;
		const i = ai[k] / m;
		re[k] = r * cr[k] - i * ci[k];
		im[k] = r * ci[k] + i * cr[k];
	}
}

/** In place: the forward transform (`sign` -1) or the unnormalised inverse. */
export function fft(re, im, sign = -1) {
	if (re.length <= 1) return;
	if (isPow2(re.length)) radix2(re, im, sign);
	else bluestein(re, im, sign);
}

/**
 * The transform of a real sequence: the `⌊N/2⌋ + 1` coefficients from zero
 * frequency up, as FFTW's `rfft` returns them.
 *
 * @returns {{re: Float64Array, im: Float64Array}}
 */
export function rfft(y) {
	const n = y.length;
	const re = Float64Array.from(y);
	const im = new Float64Array(n);
	fft(re, im, -1);
	const h = Math.floor(n / 2) + 1;
	return { re: re.slice(0, h), im: im.slice(0, h) };
}

/**
 * The inverse of `rfft` for a sequence of length `n`, divided by `n`.
 *
 * @param {{re: Float64Array, im: Float64Array}} half  the `⌊n/2⌋ + 1` coefficients
 * @param {number} n
 */
export function irfft(half, n) {
	const re = new Float64Array(n);
	const im = new Float64Array(n);
	const h = Math.floor(n / 2) + 1;
	for (let k = 0; k < h; k++) {
		re[k] = half.re[k];
		im[k] = half.im[k];
	}
	// The rest from Hermitian symmetry. The zero-frequency term, and the
	// Nyquist one of an even length, are real in any transform of real data,
	// and are read as real here whatever rounding left in them -- as FFTW's
	// c2r transform does.
	im[0] = 0;
	if (n % 2 === 0) im[n / 2] = 0;
	for (let k = h; k < n; k++) {
		re[k] = half.re[n - k];
		im[k] = -half.im[n - k];
	}
	fft(re, im, 1);
	for (let k = 0; k < n; k++) re[k] /= n;
	return re;
}

/** `|F_k|²` of `rfft(y)`, for the spectral methods. */
export function powerSpectrum(y) {
	const { re, im } = rfft(y);
	const out = new Float64Array(re.length);
	for (let k = 0; k < re.length; k++) out[k] = re[k] * re[k] + im[k] * im[k];
	return out;
}

/**
 * The orthonormal DCT-II, `X_k = w_k Σ_n y_n cos(πk(2n+1)/2N)` with
 * `w_0 = √(1/N)` and `w_k = √(2/N)` -- FFTW's `dct`. For the first `upTo`
 * coefficients only: EASI reads a handful of them and the sum of the rest,
 * which is the sum of squares by Parseval.
 */
export function dct2(y, upTo = y.length) {
	const n = y.length;
	const m = Math.min(n, upTo);
	const out = new Float64Array(m);
	for (let k = 0; k < m; k++) {
		let s = 0;
		for (let j = 0; j < n; j++) s += y[j] * Math.cos((Math.PI * k * (2 * j + 1)) / (2 * n));
		out[k] = s * Math.sqrt((k === 0 ? 1 : 2) / n);
	}
	return out;
}
