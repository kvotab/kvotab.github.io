// Panel resize handle
(function() {
  const handle = document.getElementById('resizeHandle');
  const leftPanel = document.getElementById('leftPanel');
  const container = leftPanel.parentElement;
  let startX, startWidth;

  handle.addEventListener('mousedown', function(e) {
    e.preventDefault();
    e.stopPropagation();
    startX = e.clientX;
    startWidth = leftPanel.getBoundingClientRect().width;
    handle.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    // Block pointer events on everything else during drag
    container.style.pointerEvents = 'none';
    handle.style.pointerEvents = 'auto';

    function onMouseMove(e) {
      e.preventDefault();
      const dx = e.clientX - startX;
      const maxW = container.getBoundingClientRect().width * 0.6;
      const newWidth = Math.max(150, Math.min(startWidth + dx, maxW));
      leftPanel.style.flex = '0 0 ' + newWidth + 'px';
    }

    function onMouseUp() {
      handle.classList.remove('active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      container.style.pointerEvents = '';
      handle.style.pointerEvents = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      window.dispatchEvent(new Event('resize'));
    }

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  });
})();

// Chart vertical resize handle
(function() {
  const handle = document.getElementById('chartResizeHandle');
  const chart = document.getElementById('plotlyChart');
  if (!handle || !chart) return;
  let startY, startHeight;

  handle.addEventListener('mousedown', function(e) {
    e.preventDefault();
    e.stopPropagation();
    startY = e.clientY;
    startHeight = chart.getBoundingClientRect().height;
    handle.classList.add('active');
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';

    function onMouseMove(e) {
      e.preventDefault();
      const dy = e.clientY - startY;
      const minH = parseInt(getComputedStyle(chart).minHeight) || 200;
      const maxH = 2000;
      const newHeight = Math.max(minH, Math.min(startHeight + dy, maxH));
      chart.style.height = newHeight + 'px';
    }

    function onMouseUp() {
      handle.classList.remove('active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      window.dispatchEvent(new Event('resize'));
    }

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  });
})();
