// Image niceties: the full-size lightbox and the failed-image retry.


// ---------------------------------------------------------------------------
// image lightbox: click any game image -> full-size viewer overlay
// ---------------------------------------------------------------------------

export function maybeOpenLightbox(e) {
  let img = e.target && e.target.tagName === "IMG" ? e.target : null;
  if (!img && e.target && e.target.closest) {
    // the WHOLE figure opens the image - caption plate and frame included
    // (the prose-art figcaption is pointer-events:none chrome, so its clicks
    // land on the figure, never the img). A still-loading skeleton has
    // nothing to show and stays inert.
    const fig = e.target.closest("figure.prose-art, figure.beat-image, .pm-image figure");
    if (fig && !fig.classList.contains("art-loading")) img = fig.querySelector("img");
  }
  if (!img) return;
  if (e.target.closest && e.target.closest("button")) return; // item-slot buttons keep their own click
  const src = img.getAttribute("src") || "";
  if (!src.startsWith("/")) return; // only our same-origin game media
  e.preventDefault();
  e.stopPropagation();
  // prefer the rich description a renderer attached over the bare alt name
  openLightbox(src, img.dataset.caption || img.getAttribute("alt") || "");
}

export function openLightbox(src, alt) {
  closeLightbox();
  const ov = document.createElement("div");
  ov.className = "lightbox-overlay";
  ov.setAttribute("role", "dialog");
  ov.setAttribute("aria-modal", "true");
  ov.setAttribute("aria-label", alt || "Image viewer");
  const img = document.createElement("img");
  img.src = src;
  img.alt = alt;
  ov.appendChild(img);
  // the caption is the moment's CONCEPT (1-3 sentences): clamped to one line
  // in the chat flow, shown in FULL here
  if (alt) {
    const cap = document.createElement("p");
    cap.className = "lightbox-caption";
    cap.textContent = alt;
    ov.appendChild(cap);
  }
  ov.addEventListener("click", closeLightbox); // click anywhere closes
  document.body.appendChild(ov);
  document.addEventListener("keydown", lightboxKey);
}

export function lightboxKey(e) {
  if (e.key === "Escape") closeLightbox();
}

export function closeLightbox() {
  document.querySelectorAll(".lightbox-overlay").forEach((o) => o.remove());
  document.removeEventListener("keydown", lightboxKey);
}

export function retryFailedImage(e) {
  const img = e.target;
  if (!img || img.tagName !== "IMG") return;
  const src = img.getAttribute("src") || "";
  if (!src.startsWith("/")) return; // only our same-origin game media
  const tries = Number(img.dataset.retry || 0);
  if (tries >= 3) return;
  img.dataset.retry = String(tries + 1);
  const base = src.replace(/[?&]r=\d+$/, "");
  setTimeout(() => {
    if (!img.isConnected) return;
    img.src = `${base}${base.includes("?") ? "&" : "?"}r=${tries + 1}`;
  }, 700 * (tries + 1));
}
