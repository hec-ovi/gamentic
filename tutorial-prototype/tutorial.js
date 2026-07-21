/* Gamentic guided-tour engine.
   Classic script (no modules) so index.html runs from a double-clicked file://.
   Depends on window.TUTORIAL_STEPS (steps.js) and the #tut markup in index.html.

   The spotlight is a single positioned <div> (#tutHole) with a huge box-shadow
   spread: the shadow dims the entire page while the div's own rectangle stays
   clear, giving a soft-glow cutout around any element from just its selector.
   That keeps the engine generic and dependency-free, ready to drop into the
   real app: point it at a selector, it masks everything else. */

(function () {
  "use strict";

  var steps = window.TUTORIAL_STEPS || [];
  var i = 0;
  var active = false;

  // ---- element handles ----
  var root = document.getElementById("tut");
  var hole = document.getElementById("tutHole");
  var catcher = document.getElementById("tutCatch");
  var card = document.getElementById("tutCard");
  var elRegion = document.getElementById("tutRegion");
  var elTitle = document.getElementById("tutTitle");
  var elBody = document.getElementById("tutBody");
  var elExample = document.getElementById("tutExample");
  var elNow = document.getElementById("tutNow");
  var elTotal = document.getElementById("tutTotal");
  var elDots = document.getElementById("tutDots");
  var btnBack = document.getElementById("tutBack");
  var btnNext = document.getElementById("tutNext");
  var btnSkip = document.getElementById("tutSkip");
  var replay = document.getElementById("tutReplay");

  var PAD = 8; // default breathing room around a spotlight cutout
  var GAP = 16; // gap between cutout and caption card

  // ---- overlays / revealables reset --------------------------------------
  function allOverlays() {
    return Array.prototype.slice.call(document.querySelectorAll(".tut-overlay"));
  }
  function allRevealables() {
    return Array.prototype.slice.call(document.querySelectorAll(".tut-revealable"));
  }
  function applyStage(step) {
    // open exactly the overlay this step needs (if any), hide the rest.
    // NB: classList.toggle's force arg must be a real boolean - an `undefined`
    // second arg makes it toggle instead of remove, which would leak overlays.
    allOverlays().forEach(function (o) {
      o.classList.toggle("open", Boolean(step.stage) && o.getAttribute("data-overlay") === step.stage);
    });
    // reveal only the mid-turn bits this step asks for
    var want = step.show || [];
    allRevealables().forEach(function (r) {
      var key = r.getAttribute("data-reveal");
      r.classList.toggle("shown", want.indexOf(key) !== -1);
    });
  }
  function resetStage() {
    allOverlays().forEach(function (o) { o.classList.remove("open"); });
    allRevealables().forEach(function (r) { r.classList.remove("shown"); });
  }

  // ---- dots --------------------------------------------------------------
  function buildDots() {
    elDots.innerHTML = "";
    for (var n = 0; n < steps.length; n++) {
      var d = document.createElement("button");
      d.type = "button";
      d.className = "tut-dot";
      d.setAttribute("aria-label", "Go to step " + (n + 1));
      d.dataset.index = String(n);
      d.addEventListener("click", function (e) {
        e.stopPropagation();
        go(Number(this.dataset.index));
      });
      elDots.appendChild(d);
    }
  }
  function markDots() {
    var kids = elDots.children;
    for (var n = 0; n < kids.length; n++) {
      kids[n].classList.toggle("on", n === i);
      kids[n].classList.toggle("done", n < i);
    }
  }

  // ---- positioning -------------------------------------------------------
  function positionFor(step) {
    var target = step.sel ? document.querySelector(step.sel) : null;

    if (!target) {
      // intro / outro: full dim, no cutout, card centered
      hole.style.opacity = "0";
      hole.style.width = "0px";
      hole.style.height = "0px";
      catcher.style.background = "rgba(3,6,14,0.9)";
      centerCard();
      return;
    }
    catcher.style.background = "transparent"; // the hole's box-shadow does the dimming

    var pad = step.pad != null ? step.pad : PAD;
    var r = target.getBoundingClientRect();
    var top = Math.max(4, r.top - pad);
    var left = Math.max(4, r.left - pad);
    var right = Math.min(window.innerWidth - 4, r.right + pad);
    var bottom = Math.min(window.innerHeight - 4, r.bottom + pad);

    hole.style.opacity = "1";
    hole.style.top = top + "px";
    hole.style.left = left + "px";
    hole.style.width = (right - left) + "px";
    hole.style.height = (bottom - top) + "px";

    placeCard(step, { top: top, left: left, right: right, bottom: bottom });
  }

  function centerCard() {
    card.style.top = "50%";
    card.style.left = "50%";
    card.style.transform = "translate(-50%, -50%)";
  }

  function placeCard(step, box) {
    card.style.transform = "none";
    var cw = card.offsetWidth;
    var ch = card.offsetHeight;
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var place = step.place || "auto";

    var spaceBelow = vh - box.bottom;
    var spaceAbove = box.top;
    var spaceRight = vw - box.right;
    var spaceLeft = box.left;

    var top, left;

    function horiz() {
      // horizontally align the card near the cutout, clamped to viewport
      var cx = (box.left + box.right) / 2 - cw / 2;
      return clamp(cx, 12, vw - cw - 12);
    }
    function vert() {
      var cy = (box.top + box.bottom) / 2 - ch / 2;
      return clamp(cy, 12, vh - ch - 12);
    }

    // pick a side that fits; fall back to whichever has the most room
    var order;
    if (place === "below") order = ["below", "above", "right", "left"];
    else if (place === "above") order = ["above", "below", "right", "left"];
    else if (place === "left") order = ["left", "right", "above", "below"];
    else if (place === "right") order = ["right", "left", "above", "below"];
    else order = ["below", "above", "right", "left"];

    var chosen = null;
    for (var k = 0; k < order.length; k++) {
      var side = order[k];
      if (side === "below" && spaceBelow >= ch + GAP) { chosen = side; break; }
      if (side === "above" && spaceAbove >= ch + GAP) { chosen = side; break; }
      if (side === "right" && spaceRight >= cw + GAP) { chosen = side; break; }
      if (side === "left" && spaceLeft >= cw + GAP) { chosen = side; break; }
    }
    if (!chosen) {
      // nothing fits cleanly: park it where there is the most room
      var rooms = [
        { s: "below", v: spaceBelow }, { s: "above", v: spaceAbove },
        { s: "right", v: spaceRight }, { s: "left", v: spaceLeft }
      ].sort(function (a, b) { return b.v - a.v; });
      chosen = rooms[0].s;
    }

    if (chosen === "below") { top = box.bottom + GAP; left = horiz(); }
    else if (chosen === "above") { top = box.top - GAP - ch; left = horiz(); }
    else if (chosen === "right") { left = box.right + GAP; top = vert(); }
    else { left = box.left - GAP - cw; top = vert(); }

    card.style.top = clamp(top, 12, vh - ch - 12) + "px";
    card.style.left = clamp(left, 12, vw - cw - 12) + "px";
  }

  function clamp(v, lo, hi) {
    if (hi < lo) return lo; // viewport smaller than the card: pin to top-left
    return Math.max(lo, Math.min(hi, v));
  }

  // ---- render a step -----------------------------------------------------
  function render() {
    var step = steps[i];
    applyStage(step);

    elRegion.textContent = step.region || "Tour";
    elTitle.textContent = step.title || "";
    elBody.textContent = step.body || "";
    if (step.example) {
      elExample.textContent = step.example;
      elExample.style.display = "";
    } else {
      elExample.textContent = "";
      elExample.style.display = "none";
    }
    elNow.textContent = String(i + 1);
    elTotal.textContent = String(steps.length);
    btnBack.disabled = i === 0;
    btnNext.textContent = i === steps.length - 1 ? "Done" : "Next";
    markDots();

    // scroll the target into view (instant, so we can measure straight away),
    // then position after layout settles.
    var target = step.sel ? document.querySelector(step.sel) : null;
    if (target && target.scrollIntoView) {
      try { target.scrollIntoView({ block: "center", inline: "center", behavior: "instant" }); }
      catch (e) { target.scrollIntoView(); }
    }
    // two frames: one for the scroll/overlay to apply, one to measure clean.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { positionFor(step); });
    });
  }

  function reposition() {
    if (!active) return;
    positionFor(steps[i]);
  }

  // ---- navigation --------------------------------------------------------
  function go(n) {
    if (n < 0) n = 0;
    if (n >= steps.length) { finish(); return; }
    i = n;
    render();
  }
  function next() { if (i >= steps.length - 1) finish(); else go(i + 1); }
  function back() { go(i - 1); }

  function start() {
    if (!steps.length) return;
    active = true;
    i = 0;
    root.hidden = false;
    replay.hidden = true;
    document.body.classList.add("tut-open");
    render();
  }
  function finish() {
    active = false;
    root.hidden = true;
    resetStage();
    document.body.classList.remove("tut-open");
    replay.hidden = false;
  }

  // ---- wiring ------------------------------------------------------------
  btnNext.addEventListener("click", function (e) { e.stopPropagation(); next(); });
  btnBack.addEventListener("click", function (e) { e.stopPropagation(); back(); });
  btnSkip.addEventListener("click", function (e) { e.stopPropagation(); finish(); });
  replay.addEventListener("click", start);

  // click anywhere (the catcher, or the dimmed hole) advances; the card
  // swallows its own clicks so its buttons/dots don't double-fire.
  catcher.addEventListener("click", next);
  hole.addEventListener("click", next);
  card.addEventListener("click", function (e) { e.stopPropagation(); });

  document.addEventListener("keydown", function (e) {
    if (!active) return;
    if (e.key === "ArrowRight" || e.key === " " || e.key === "Enter") { e.preventDefault(); next(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); back(); }
    else if (e.key === "Escape") { e.preventDefault(); finish(); }
  });

  window.addEventListener("resize", reposition);
  window.addEventListener("scroll", reposition, true); // capture: catch nested scrollers

  // ---- boot --------------------------------------------------------------
  buildDots();
  // let fonts/layout settle before the first measurement
  window.addEventListener("load", function () { setTimeout(start, 60); });
  if (document.readyState === "complete") setTimeout(start, 60);
})();
