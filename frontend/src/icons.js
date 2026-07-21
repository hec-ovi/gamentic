export function icon(name) {
  const paths = {
    sigil: '<path d="M12 2 4 7v10l8 5 8-5V7l-8-5Z"/><path d="m8 9 4-3 4 3-4 9-4-9Z"/><path d="M8 9h8"/>',
    library: '<path d="M4 19.5V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-1.5Z"/><path d="M8 7h6"/><path d="M8 11h8"/>',
    sparkles: '<path d="m12 3 1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9L12 3Z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>',
    swords: '<path d="m14.5 17.5 3 3 3-3-3-3"/><path d="M3 3l10 10"/><path d="m19 3-8.5 8.5"/><path d="m6.5 17.5-3 3-3-3 3-3"/><path d="m13 13 4.5 4.5"/><path d="m11 13-4.5 4.5"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15Z"/>',
    // lucide "settings" (ISC): the old hand-rolled gear spanned 18x20 with
    // flat-clipped top/bottom teeth, so it rendered tall and lumpy at icon size
    settings: '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>',
    volume2: '<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15 9.3a4 4 0 0 1 0 5.4"/><path d="M17.7 6.6a8 8 0 0 1 0 10.8"/>',
    volumeX: '<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="m19 9-6 6"/><path d="m13 9 6 6"/>',
    panel: '<path d="M3 5h18v14H3z"/><path d="M15 5v14"/><path d="M7 9h4"/><path d="M7 13h4"/>',
    plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
    copy: '<path d="M8 8h12v12H8z"/><path d="M4 16V4h12"/>',
    star: '<path d="m12 2 3 6 6 .9-4.5 4.4 1 6.2L12 16.4 6.5 19.5l1-6.2L3 8.9 9 8l3-6Z"/>',
    scroll: '<path d="M8 21h8"/><path d="M12 17v4"/><path d="M6 3h12v10a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4V3Z"/><path d="M9 7h6"/><path d="M9 11h6"/>',
    gem: '<path d="M6 3h12l4 6-10 12L2 9l4-6Z"/><path d="M2 9h20"/><path d="m12 21 4-12-4-6-4 6 4 12Z"/>',
    play: '<path d="m8 5 11 7-11 7V5Z"/>',
    trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5"/><path d="M14 11v5"/>',
    rotate: '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
    send: '<path d="m22 2-7 20-4-9-9-4 20-7Z"/><path d="M22 2 11 13"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    landmark: '<path d="M3 21h18"/><path d="M4 10h16"/><path d="M6 10v8"/><path d="M10 10v8"/><path d="M14 10v8"/><path d="M18 10v8"/><path d="m12 3 8 5H4l8-5Z"/>',
    zap: '<path d="M13 2 3 14h8l-1 8 11-14h-8l1-6Z"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    mask: '<path d="M4 8c2-3 5-4 8-4s6 1 8 4v6c0 4-3 6-8 6s-8-2-8-6V8Z"/><path d="M8 11h3"/><path d="M13 11h3"/><path d="M9 16c2 1 4 1 6 0"/>',
    mic: '<path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z"/><path d="M19 11a7 7 0 0 1-14 0"/><path d="M12 18v4"/><path d="M8 22h8"/>',
    radio: '<path d="M4.9 19.1a10 10 0 1 1 14.2 0"/><path d="M8.5 15.5a5 5 0 1 1 7 0"/><circle cx="12" cy="12" r="1"/>',
    check: '<path d="m20 6-11 11-5-5"/>',
    flame: '<path d="M12 22c4 0 7-3 7-7 0-5-4-7-5-12-2 3-6 5-6 10 0 2 1 4 4 4-1-2 0-4 2-6 1 3 3 4 3 7 0 2-2 4-5 4Z"/>',
    key: '<path d="M21 2 11 12"/><path d="M15 6l3 3"/><path d="M8 15a4 4 0 1 1-2.8-6.8A4 4 0 0 1 8 15Z"/><path d="m7 17-2 2"/><path d="m4 20-1 1"/>',
    compass: '<circle cx="12" cy="12" r="10"/><path d="m16 8-2.8 6.2L8 16l2.8-6.2L16 8Z"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    gauge: '<path d="M12 14l3.5-3.5"/><path d="M20.2 15.5a8.5 8.5 0 1 0-16.4 0"/><path d="M3.8 15.5h2"/><path d="M18.2 15.5h2"/>',
    at: '<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>',
  };

  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.sparkles}</svg>`;
}
