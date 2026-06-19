# NexPatchbay

NexPatchbay is a Python and Qt patchbay component maintained for
[NexSession](https://github.com/SamuelSJames/NexSession). It provides the
canvas, routing model, JACK widgets, filtering, and patchbay dialogs used by
NexSession. It is a reusable component rather than a standalone application.

## Origin and attribution

NexPatchbay is based on
[HoustonPatchbay](https://github.com/Houston4444/HoustonPatchbay), created by
Mathieu Picot (Houston4444). The original Git history is preserved in this
repository so authorship and project lineage remain available.

NexPatchbay is distributed under the GNU General Public License version 2.
See [LICENSE](LICENSE).

## Integration

NexSession integrates the component through
`src/gui/nex_patchbay_manager.py`. Applications embed a graphics view promoted
to `PatchGraphicsView`, derive their manager from `PatchbayManager` and
`Callbacker`, and call `PatchbayManager.app_init()` after initialization.

The component includes:

- a patchbay canvas and connection model;
- canvas and JACK server controls;
- audio and MIDI filtering;
- global context menus;
- port and group information dialogs; and
- reusable patchbay widgets.

The API may evolve with NexSession. Consumers should pin a known Git commit.
