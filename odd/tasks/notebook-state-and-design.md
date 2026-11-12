# Preserve notebook projects and unchanged designs
Branch: `feat/colab-youtube-backgrounds`; delivery: ask-on-risk, separate local commits, no publishing; forecast: about 350 authored lines for the remaining fixes.
Verification: executable notebook logic probes outside the workspace, Ruff, focused Python services; real Colab interaction requires separate remote-access authorization.

## Specs

- S1: "haz commit de tu cambio anterior" — commit only the preceding selected-model language detection and cache change, preserving unrelated staged and unstaged work.
- S2: "y luego haz lo mismo al solucionar 2, 4, 5" — item 2 is the accepted suggestion "Evitar perder el proyecto activo al editar el formulario". Retain successful outputs, ignore retired-form callbacks, and reject rendering when current song inputs no longer match the prepared project.
- S3: "y luego haz lo mismo al solucionar 2, 4, 5" — item 4 is the accepted suggestion "Abrir los controles de diseño todavía exige aplicarlos aunque no hayas cambiado nada." Opening unchanged controls must preserve the saved appearance and permit rendering; real unapplied changes remain blocked.
- S4: "Incluir el panel de diseño" — include the necessary pre-existing notebook design panel and its documentation in the item-4 commit, excluding release, branding, and unrelated work.
- S5: "y luego haz lo mismo al solucionar 2, 4, 5" — item 5 is "Falta comprobar el flujo nuevo completo: detección, corrección manual, preparación, render y descarga." Verify actual Colab/browser interaction only after the destination, operation, and session/credential are explicitly authorized. Local probes do not satisfy this spec.

## Tasks

- T0 [S1] inline; completed; commit `63fa5b4`; isolated snapshot: 59 tests passed; prior shared-loader verification remains recorded in memory.
- T1 [S2] inline; completed; commit `458d2bd`; no writer trigger: one coupled form/preparation behavior; RED lost outputs, GREEN callback/snapshot/failure probes and Ruff on the isolated commit candidate.
- T2 [S3-S4] inline; focused checks passed, final suite pending; commit pending; same notebook surface requires sequential work, not parallel writers.
- T3 [S5] inline orchestration; blocked on remote session/access authorization; evidence and verification commit pending.

## Log

- L1: User request verbatim: "haz commit de tu cambio anterior, y luego haz lo mismo al solucionar 2, 4, 5".
- L2: User selected "Incluir el panel de diseño" after the exact question "Para corregir y guardar el punto 4, ¿autorizas incluir en ese commit los cambios previos del panel de diseño de notebooks/generate_video.ipynb y su documentación necesaria? Quedarían fuera los cambios de publicación, branding y demás trabajo ajeno."
- L3: Existing staged logo deletions and extensive release/branding/reference changes are outside scope. T0 used an isolated index; staged logo deletions remained unchanged. No push or publication is authorized by local commit requests.
- L4: RDD is globally disabled. Do not enable it. Wrong-song lyric acceptance and checkpoint/project import are not included in these tasks.
- L5: T1 keeps successful project/video pointers while inputs differ, blocks stale rendering, ignores retired forms, restores compatibility on reversion, and only replaces outputs after a successful matching attempt. Metadata lookup inputs conservatively require re-preparation; the previous editable project remains exportable. Mixed CRLF notebook lines were normalized before functional checks.
- L6: T1 commit `458d2bd` excludes the existing design/release/branding changes. T0 and T1 left the three staged logo deletions unchanged. Risk: none (notebook-local state behavior).
- L7: T2 RED reproduced missing saved-design inspection and false pending state on opening. GREEN: 22 focused service tests, saved solid/fluid/cosmic/image/video logic probes, changed/reverted/retired-form checks, retained render on failure, and Ruff. The JSON inspection adds optional saved-design data; rendering no longer reapplies presets over the saved document. Local probes are not browser/Colab proof.
