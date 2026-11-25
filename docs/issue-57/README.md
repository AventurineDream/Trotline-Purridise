# V1-29 evidence: cats, portraits and the Skipper

Captured on commit 91d3e38 with Mesa llvmpipe, which caps native frames at 640×360. There is no hardware GPU here.

- **`native/`** is `python -m fishing --shots docs/issue-57/native --cats`. It holds GL and software frames of the world, plus the CPU-rendered sheets.
- **`software-cats-benchmark.json`** is the `--software` run of the same capture. That run renders no GL frames.
- **`benchmark-native.json` and `benchmark-software.json`** are the full-frame benchmark (`--benchmark 1200`), with `cat_actor_memory`.

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| A `--shots` lineup of all 52 cats with their portraits | `native/cats-lineup.png`: 51 actors, with Pip & Pebble as one. Each figure is above its 256×256 portrait. Portraits alone are in `native/cats-portraits.png`. The capture fails unless the roster holds 52 cats. |
| NPCs visible in the world on both existing lakes | `native/cats-world.png` and `native/world-<lake>-<npc>-{approach,hail,close}-{native,software}.png`. Briar: Grandmother Whiskers on the landing pier, Elder Moss on his log raft. Cedar: Doc Barnaby on a float at his dock anchor, Captain Maeve in her mahogany runabout. Every approach and hail frame has the cat's hail available. |
| At most 14 actors resident, within 150 MB | In `native/benchmark.json` → `budget`, 20 cats queued on Briar's anchors keep 14 resident. The peak bound is 16,971,274 bytes; the GL renderer adds 11,114,152 bytes of fixed slot and atlas reserves. The full-frame benchmarks fail past 14 actors or 150 MiB; their peak bounds were 20.2 MB (GL) and 7.9 MB (software). |
| Hailing range and behaviour unchanged (20 m, below 3 knots) | `native/benchmark.json` → `hailing`: hailing works at 19.5 m and not at 20.5 m; at 10 m it works just under 1.5433 m/s and not at it. `dialogue.py` is unchanged. |

## The other sheets

- **`cats-poses.png`:** the five poses, plus a sitting cat blending into its wave (0, 0.5 and 1).
- **`cats-patterns.png`:** one cat for each of the nine coat patterns.
- **`cats-lod.png`:** LOD0, LOD1 and the impostor for four cats, including Pip & Pebble.
- **`skipper.png`:** the paws in both renderers:
  - on the jon boat's tiller and the rowboat's oars;
  - on the rowboat's tiller and an oar, with the trolling motor;
  - on a tiller extension (sailboat, river runner), a paddle (log raft) and oars (dory);
  - on the line during a haul;
  - followed by the head reflection when idle and when moving.
- **`reflection-{idle,moving}-{native,software}.png`:** the Skipper's head silhouette on calm water at idle (ears down, past the bow), gone once under way.
- **`dialogue-portrait-{briar,cedar}.png`:** the host's portrait at the left of the dialogue panel, at 1280×720.
- **`chart-pins-{briar,cedar}.png`:** the chart as captured for this issue, with pins in each cat's coat colour. Issue #159 later moved pins to a chart-only palette; these sheets predate that.

## Numbers

- **Triangles.** LOD0: 2,052–2,672 (median 2,320). LOD1: 642–874 (median 750). Pip & Pebble: 4,464 and 1,404.
- **Build cost.** On the CPU, a cat's mesh build (both LODs) is 54.9 ms at the median, and a portrait 42.3 ms.
- **Peak RSS.** 401 MiB for the native capture and 271 MiB for the software one.
- **Frame time.** Main (5fb5da4) was benchmarked on the same machine, one benchmark at a time:

| `--benchmark 1200` | main render / full frame (p95) / peak RSS | this branch |
| --- | --- | --- |
| Software | 239.57 / 345.57 (533.56) ms / 272.0 MiB | 241.44 / 348.75 (515.24) ms / 272.6 MiB |
| llvmpipe | 78.56 / 204.52 (400.82) ms / 500.8 MiB | 82.83 / 204.56 (433.70) ms / 519.9 MiB |

The benchmark's camera spots are all over 120 m from the cats. Its frames therefore carry the cats' boats, cache and impostors, not their close meshes; the cat capture covers those. On the CPU, a near cat adds about 2–17 ms to a frame, mostly for its boat's faces.

## Limitations

- **Mesa llvmpipe only, and no interactive play.** The cats were judged from these captures.
- **A cat's arrival costs a hitch.** Building its meshes and impostor on the CPU takes about 100 ms. Its first portrait takes about 40 ms.
