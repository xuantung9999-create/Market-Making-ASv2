/* desk_pending.js: placeholders for Desk views not built yet. Every view now has its own file; kept so a future
   view can be registered here first and moved out when it is built (list the view ids below). */
[].forEach(v => {
  if (!draw[v]) register(v, () => deskBundle(v));
});
