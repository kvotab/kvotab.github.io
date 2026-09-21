/**
 * A wheel's delta in pixels, whatever units it arrived in.
 *
 * Its own module because both zoomable things need the same rule, and neither
 * has any business importing the other: the diagram is 4,000 lines of graph
 * editor and the chart is a canvas plot.
 */

/**
 * `deltaMode` is the whole difference between a trackpad and a mouse. A
 * trackpad reports pixels, a hundred or so per gesture; a wheel reports
 * *lines*, three per notch. Taking the number at face value made one notch
 * worth three pixels -- a zoom of half a percent -- so on a mouse the canvas
 * looked as though it did not zoom at all.
 *
 * The result is clamped so a page-sized delta, or a hard fling, moves by a
 * step you can still follow rather than jumping the length of the range.
 */
export function wheelPixels(deltaY, deltaMode, viewport = 600) {
	const LINE = 16;
	// 1 is DOM_DELTA_LINE, 2 is DOM_DELTA_PAGE.
	const scale = deltaMode === 1 ? LINE : deltaMode === 2 ? viewport : 1;
	return Math.max(-240, Math.min(240, (deltaY || 0) * scale));
}
