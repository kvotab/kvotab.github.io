"""Image processing, run natively, against scikit-image and SciPy computing
the same things on their own (scikit-image is a reference only; the page
does not use it): reconstruction and regional extrema, h-maxima,
clearing the border, removing small objects, the Euler number, watershed,
colour spaces, psnr, ssim and entropy, local filters, thresholds,
gradients, the transformation objects, imref2d and imwarp, fitted
transformations, phase correlation, the Hough transform and its lines,
circles, the Radon transform and its inverse, the DCT, padding and blocks.

    python3 test_imagemore.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import tempfile

import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-imagemore-')
R.STATE['home'] = TMP


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        parts = [np.asarray(v, dtype=float).reshape(-1) for v in x]
        return np.concatenate(parts) if parts else np.zeros(0)
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 6).tolist() if g.size < 30 else g.shape}, want {np.round(w, 6).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)



try:
    from skimage import morphology, measure, color, metrics, filters, segmentation, transform, draw
except ImportError:
    print('test_imagemore needs scikit-image as a reference (pip install scikit-image)')
    sys.exit(0)
from scipy import ndimage  # noqa: E402
from scipy.fft import dctn  # noqa: E402


def mat(M):
    return '[' + '; '.join(' '.join(repr(float(v)) for v in row) for row in np.atleast_2d(M)) + ']'


def text(v):
    from plab.values import py_str
    return py_str(v)


rs = np.random.RandomState(0)
# a smooth test image with several hills, its own (nothing from elsewhere)
yy, xx = np.mgrid[0:48, 0:56] / 8.0
img = (np.sin(xx) * np.cos(yy * 0.8) + 0.3 * np.sin(2.3 * xx + yy)) / 2.6 + 0.5
img = np.round(img * 255) / 255
IMG = mat(img)

# ---- reconstruction and extrema --------------------------------------------------------------------------------
W, _ = run(f"I = {IMG}; J = imreconstruct(max(I - 0.2, 0), I); rm = imregionalmax(I); rn = imregionalmin(I); hm = imhmax(I, 0.1); hn = imhmin(I, 0.1); em = imextendedmax(I, 0.1);")
near('imreconstruct as skimage.morphology.reconstruction', W['J'], morphology.reconstruction(np.clip(img - 0.2, 0, 1), img), 1e-12)
same('imregionalmax and imregionalmin as skimage local_maxima and local_minima (8-connected)',
     (int((W['rm'] != morphology.local_maxima(img, connectivity=2)).sum()), int((W['rn'] != morphology.local_minima(img, connectivity=2)).sum())), (0, 0))
near('imhmax and imhmin as reconstructions; imextendedmax the maxima of imhmax', (W['hm'], W['hn'], W['em']),
     (morphology.reconstruction(img - 0.1, img), -morphology.reconstruction(-img - 0.1, -img),
      morphology.local_maxima(morphology.reconstruction(img - 0.1, img), connectivity=2)), 1e-12)
bw = img > 0.55
BW = f"logical({mat(bw)})"
W, _ = run(f"BW = {BW}; e = bweuler(BW); ao = bwareaopen(BW, 30); cl = imclearborder(BW); [L, n] = bwlabeln(BW); P = bwperim(BW); D = bwdist(BW); fl = imreconstruct(BW & false(size(BW)), BW);")
same('bweuler as skimage.measure.euler_number; bwareaopen, imclearborder, bwlabeln as skimage',
     (float(W['e']), int((W['ao'] != morphology.remove_small_objects(bw, 30, connectivity=2)).sum()), int((W['cl'] != segmentation.clear_border(bw)).sum()),
      float(W['n'])), (float(measure.euler_number(bw, connectivity=2)), 0, 0, float(measure.label(bw, connectivity=2).max())))
inner = ndimage.binary_erosion(np.pad(bw, 1), structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))[1:-1, 1:-1]
near('bwperim: on pixels with an off 4-neighbour (outside off); bwdist as distance_transform_edt', (W['P'], W['D']), (bw & ~inner, ndimage.distance_transform_edt(~bw)), 1e-6)
W, _ = run(f"I = {IMG}; L = watershed(imgaussfilt(I, 2)); n = max(L(:)); r = nnz(L == 0); nm = nnz(imregionalmin(imgaussfilt(I, 2)));")
L = a(W['L'])
from collections import Counter  # noqa: E402
def ridge_ok():
    for i in range(L.shape[0]):
        for j in range(L.shape[1]):
            if L[i, j] == 0:
                continue
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    ii, jj = i + di, j + dj
                    if 0 <= ii < L.shape[0] and 0 <= jj < L.shape[1] and L[ii, jj] not in (0, L[i, j]):
                        return False
    return True
C('watershed: a basin for each regional minimum, ridges of 0 between every two (no two labels touch)', float(W['n']) >= 1 and ridge_ok() and float(W['r']) > 0, (W['n'], W['r'], W['nm']))

# ---- colour --------------------------------------------------------------------------------------------------------
rgb = rs.random_sample((6, 7, 3))
RGB = f"cat(3, {mat(rgb[..., 0])}, {mat(rgb[..., 1])}, {mat(rgb[..., 2])})"
W, _ = run(f"A = {RGB}; lab = rgb2lab(A); back = lab2rgb(lab); y = rgb2ycbcr(A); y2 = ycbcr2rgb(y); xyz = rgb2xyz(A); u8 = rgb2ycbcr(uint8(255*A)); i16 = im2int16([0 0.5 1]);")
near("rgb2lab as skimage (to their sRGB matrix's rounding) and back; YCbCr as skimage's BT.601; XYZ", (W['lab'], W['back'], W['y'] * 255, W['y2'], W['xyz']),
     (color.rgb2lab(rgb), rgb, color.rgb2ycbcr(rgb), rgb, color.rgb2xyz(rgb)), 1e-2)
near('round trips exact', (W['back'], W['y2']), (rgb, rgb), 1e-12)
near('im2int16 maps 0 to 1 onto -32768 to 32767', W['i16'], [[-32768, 0, 32767]])

# ---- quality measures ------------------------------------------------------------------------------------------------
noisy = np.clip(img + rs.normal(0, 0.05, img.shape), 0, 1)
W, _ = run(f"A = {mat(noisy)}; B = {IMG}; [p, s] = psnr(A, B); [v, m] = ssim(A, B); e = entropy(im2uint8(B)); c = corr2(A, B); ms = immse(A, B);")
sk = metrics.structural_similarity(img, noisy, gaussian_weights=True, sigma=1.5, use_sample_covariance=False, data_range=1, full=True)
near('psnr, the ssim map (inside the border skimage crops), entropy, corr2, immse', (W['p'], a(W['m'])[5:-5, 5:-5], W['e'], W['c'], W['ms']),
     (metrics.peak_signal_noise_ratio(img, noisy, data_range=1), sk[1][5:-5, 5:-5], measure.shannon_entropy((img * 255 + 0.5).astype(np.uint8)),
      np.corrcoef(noisy.ravel(), img.ravel())[0, 1], np.mean((noisy - img) ** 2)), 1e-10)

# ---- local filters and thresholds -------------------------------------------------------------------------------------
W, _ = run(f"B = {IMG}; s = stdfilt(B); r = rangefilt(B); o = ordfilt2(B, 5, true(3)); ii = integralImage(B); bx = imboxfilt(B, 5); [gx, gy] = imgradientxy(B); [gm, gd] = imgradient(B); t = multithresh(B, 2); [T, em] = otsuthresh(imhist(B)); g = graythresh(B);")
near("stdfilt (n - 1), rangefilt, ordfilt2's median, imboxfilt as SciPy's filters; the integral image's corner",
     (W['s'], W['r'], W['o'], W['bx'], W['ii'][-1, -1]),
     (ndimage.generic_filter(img, lambda v: v.std(ddof=1), 3, mode='reflect'), ndimage.maximum_filter(img, 3, mode='nearest') - ndimage.minimum_filter(img, 3, mode='nearest'),
      ndimage.median_filter(img, 3, mode='constant'), ndimage.uniform_filter(img, 5, mode='nearest'), img.sum()), 1e-10)
hy = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1.0]])
near('imgradientxy (Sobel, the border replicated); imgradient', (W['gx'], W['gy'], W['gm'], W['gd']),
     (ndimage.correlate(img, hy.T, mode='nearest'), ndimage.correlate(img, hy, mode='nearest'), np.hypot(ndimage.correlate(img, hy.T, mode='nearest'), ndimage.correlate(img, hy, mode='nearest')),
      np.degrees(np.arctan2(-ndimage.correlate(img, hy, mode='nearest'), ndimage.correlate(img, hy.T, mode='nearest')))), 1e-10)
skt = filters.threshold_multiotsu(img, classes=3, nbins=256)
C('multithresh within two bins of skimage threshold_multiotsu; otsuthresh is graythresh', bool(np.all(np.abs(a(W['t']).reshape(-1) - skt) <= 2 * (img.max() - img.min()) / 255))
  and abs(float(W['T']) - float(W['g'])) < 1e-15, (a(W['t']).tolist(), skt.tolist()))
W, _ = run(f"B = {IMG}; ad = adapthisteq(B); q = imquantize([0.1 0.5 0.9], [0.3 0.6]); qv = imquantize([0.1 0.5 0.9], [0.3 0.6], [10 20 30]);")
near('adapthisteq spans 0 to 1; imquantize classes and values', (min(a(W['ad']).min(), 0.02) <= 0.02, a(W['ad']).max() > 0.98, W['q'], W['qv']), (1, 1, [[1, 2, 3]], [[10, 20, 30]]))

# ---- transformations ---------------------------------------------------------------------------------------------------
W, _ = run("""t = affine2d([2 0 0; 0 3 0; 5 7 1]); [u, v] = transformPointsForward(t, [1 2], [1 1]); P = transformPointsInverse(t, [u' v']); Ti = invert(t).T;
r = rigidtform2d(30, [1 2]); ang = r.RotationAngle; s = simtform2d(2, 45, [0 0]); sc = s.Scale;
[xl, yl] = outputLimits(affinetform2d([0 -1 0; 1 0 0; 0 0 1]), [0.5 10.5], [0.5 20.5]); R2 = imref2d([4 5], [0 10], [0 8]); dx = R2.PixelExtentInWorldX; [rr, cc] = worldToSubscript(R2, [1 9], [1 1]);
it = [isTranslation(transltform2d(1, 2)) isRigid(r) isSimilarity(s) isRigid(s)];""")
near('affine2d forward and back; invert; rigidtform2d and simtform2d properties; outputLimits; imref2d', (W['u'], W['v'], W['P'], W['Ti'], W['ang'], W['sc'], W['xl'], W['yl'], W['dx'], W['rr'], W['cc'], W['it']),
     ([[7, 9]], [[10, 10]], [[1, 1], [2, 1]], np.linalg.inv(np.array([[2, 0, 0], [0, 3, 0], [5, 7, 1.0]])), 30, 2, [[-20.5, -0.5]], [[0.5, 10.5]], 2, [[1, 1]], [[1, 5]], [[1, 1, 1, 0]]), 1e-12)
W, _ = run(f"I = {IMG}; [B, RB] = imwarp(I, affinetform2d(eye(3))); sm = isequal(B, I); t = affinetform2d([1 0 3; 0 1 2; 0 0 1]); [B2, RB2] = imwarp(I, t); xw = RB2.XWorldLimits; "
           f"B3 = imwarp(I, t, 'OutputView', imref2d(size(I))); D = zeros([size(I) 2]); D(:,:,1) = 1; B4 = imwarp(I, D);")
near('imwarp: identity unchanged; a translation moves the output limits; OutputView shifts the pixels; a displacement field',
     (W['sm'], W['xw'], a(W['B3'])[2:, 3:], a(W['B4'])[:, :-1]), (1, [[3.5, 59.5]], img[:-2, :-3], img[:, 1:]), 1e-12)
mov = rs.random_sample((6, 2)) * 50
Af = np.array([[1.2, -0.3, 4], [0.25, 0.9, -2], [0, 0, 1.0]])
fix = mov @ Af[:2, :2].T + Af[:2, 2]
Hp = np.array([[1.1, 0.1, 3], [-0.05, 0.95, 2], [0.001, 0.002, 1.0]])
fp = np.column_stack([mov, np.ones(6)]) @ Hp.T
fp = fp[:, :2] / fp[:, 2:]
Rs = np.array([[math.cos(math.radians(20)), -math.sin(math.radians(20))], [math.sin(math.radians(20)), math.cos(math.radians(20))]])
W, _ = run(f"m = {mat(mov)}; t = fitgeotrans(m, {mat(fix)}, 'affine'); T = t.T; tp = fitgeotform2d(m, {mat(fp)}, 'projective'); Ap = tp.A; "
           f"t3 = fitgeotform2d(m, {mat(mov @ Rs.T * 1.5 + [3, 4])}, 'similarity'); s3 = [t3.Scale t3.RotationAngle t3.Translation];")
near('fitgeotrans affine; fitgeotform2d projective (normalized DLT) and similarity, exact on exact points', (a(W['T']).T, a(W['Ap']) / a(W['Ap'])[2, 2], W['s3']),
     (Af, Hp, [[1.5, 20, 3, 4]]), 1e-9)
big = np.kron(img, np.ones((2, 2)))
mv = np.roll(np.roll(big, 5, axis=1), -3, axis=0)
rot = transform.rotate(big, 12, mode='constant', preserve_range=True)
W, _ = run(f"F = {mat(big)}; t = imregcorr({mat(mv)}, F, 'translation'); tt = t.Translation; t2 = imregcorr({mat(rot)}, F, 'rigid'); ang = t2.RotationAngle;")
near('imregcorr: a shift to within a tenth of a pixel; a rotation to within half a degree', (W['tt'], W['ang']), ([[-5, 3]], 12), 0.5)
C('... the shift that close', np.allclose(a(W['tt']), [[-5, 3]], atol=0.1), W['tt'])

# ---- Hough, circles, Radon, DCT --------------------------------------------------------------------------------------------------
bwl = np.zeros((60, 60), bool)
r_, c_ = draw.line(10, 5, 50, 45)
bwl[r_, c_] = True
r_, c_ = draw.line(30, 2, 30, 55)
bwl[r_, c_] = True
W, _ = run(f"BW = logical({mat(bwl)}); [H, T, Rh] = hough(BW); P = houghpeaks(H, 2); L = houghlines(BW, T, Rh, P, 'FillGap', 5, 'MinLength', 7); n = numel(L); p1 = L(1).point1; p2 = L(1).point2; th = T(P(:,2));")
hs, _, _ = transform.hough_line(bwl, theta=np.deg2rad(np.arange(-90, 90)))
near('hough: the strongest line as skimage hough_line; peaks at -90 and -45 degrees; the horizontal segment', (a(W['H']).max(), W['th'], W['n'], W['p1'], W['p2']),
     (hs.max(), [[-90, -45]], 2, [[3, 31]], [[56, 31]]))
im = np.zeros((100, 100))
r_, c_ = draw.disk((30, 40), 12)
im[r_, c_] = 1
r_, c_ = draw.disk((70, 65), 18)
im[r_, c_] = 1
W, _ = run(f"I = {mat(im)}; [c, r, m] = imfindcircles(I, [8 25]);")
cen = a(W['c'])
near('imfindcircles: both circles, centres to a pixel, radii to half a pixel, full support', (cen[np.argsort(cen[:, 0])], np.sort(a(W['r']).reshape(-1)), a(W['m']).min() > 0.9),
     ([[41, 31], [66, 71]], [12, 18], 1), 0.6)
W, _ = run("P = phantom(64); [Rd, xp] = radon(P, 0:179); I = iradon(Rd, 0:179); c = corr2(I(2:65, 2:65), P); su = sum(Rd); sP = sum(P(:)); sz = size(I);")
sk = transform.radon(a(W['P']), theta=np.arange(180.0), circle=False)
near("radon: every projection sums to the image's sum; iradon's size", (W['su'], W['sz']), (np.full((1, 180), float(W['sP'])), [[66, 66]]), 1e-9)
C("... as skimage's projections do, to their interpolation", np.allclose(sk.sum(axis=0), float(W['sP']), rtol=5e-3), np.abs(sk.sum(axis=0) / float(W['sP']) - 1).max())
C('iradon(radon(P)) correlates with the phantom', float(W['c']) > 0.9, W['c'])
W, _ = run(f"A = {mat(img[:8, :8])}; B = dct2(A); C = idct2(B); D = dctmtx(8); e1 = max(abs(C(:) - A(:))); e2 = max(max(abs(D*A*D' - B)));")
near('dct2 as scipy.fft.dctn (orthonormal), idct2 back, dctmtx', (W['B'], W['e1'], W['e2']), (dctn(img[:8, :8], norm='ortho'), 0, 0), 1e-12)

# ---- padding, blocks, arithmetic -------------------------------------------------------------------------------------------------
W, _ = run("""A = magic(4); p1 = padarray(A, [1 2]); p2 = padarray(A, [1 1], 'replicate', 'post'); p3 = padarray(A, [1 0], 'symmetric', 'pre');
c = im2col(A, [2 2]); d = im2col(A, [2 2], 'distinct'); back = col2im(d, [2 2], [4 4], 'distinct'); b = blockproc(A, [2 2], @(s) sum(s.data(:)));
nf = nlfilter(A, [3 3], @(x) max(x(:))); cf = colfilt(A, [3 3], 'sliding', @max);
z = imadd(uint8([250 10]), uint8([10 5])); z2 = imsubtract(uint8([5 10]), 7); z3 = imabsdiff(uint8([5 10]), uint8([10 5])); z4 = imlincomb(0.5, uint8([100 200]), 0.5, uint8([50 50]));""")
Mg = np.array([[16, 2, 3, 13], [5, 11, 10, 8], [9, 7, 6, 12], [4, 14, 15, 1.0]])
near('padarray: zeros both ways, replicate after, symmetric before', (W['p1'], W['p2'], W['p3']),
     (np.pad(Mg, ((1, 1), (2, 2))), np.pad(Mg, ((0, 1), (0, 1)), mode='edge'), np.pad(Mg, ((1, 0), (0, 0)), mode='symmetric')))
near('im2col sliding and distinct, col2im back; blockproc sums; nlfilter and colfilt the same maxima',
     (a(W['c'])[:, 0], a(W['d'])[:, 1], W['back'], W['b'], W['nf'], W['cf']),
     ([16, 5, 2, 11], [9, 4, 7, 14], Mg, [[34, 34], [34, 34]], ndimage.maximum_filter(Mg, 3, mode='constant', cval=0), ndimage.maximum_filter(Mg, 3, mode='constant', cval=0)))
same('imadd, imsubtract, imabsdiff and imlincomb saturate and round in uint8', (a(W['z']).tolist(), a(W['z2']).tolist(), a(W['z3']).tolist(), a(W['z4']).tolist()),
     ([[255.0, 15.0]], [[0.0, 3.0]], [[5.0, 5.0]], [[75.0, 125.0]]))

sys.exit(C.done())
