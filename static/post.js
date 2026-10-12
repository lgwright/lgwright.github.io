// Post page behaviour: the BibTeX copy button. The comparison galleries are in gallery.js,
// an exact copy of the personal site's static/gallery.js (sync_shared.py).
document.querySelectorAll("button.copy").forEach(function (b) {
  b.addEventListener("click", function () {
    var text = document.getElementById(b.dataset.copy).textContent;
    navigator.clipboard.writeText(text).then(function () {
      b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy BibTeX"; }, 1500);
    });
  });
});
