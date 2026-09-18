# Agent OS — dark interaction prototype

A browser-based design prototype for the flow: select a note → type or speak an instruction → review and correct the interpretation → arrange references → stop/resume/undo.

## Preview

From this directory, run `python3 -m http.server 8771 --bind 127.0.0.1`, then open http://127.0.0.1:8771.

Commissioner and its OFL license are bundled locally. There are no frontend dependencies or remote font requests. Wallpaper is a generated project asset reused from the earlier concepts.

## Try it

1. Choose **Use as context** on the note.
2. Type **Put the references beside this note**, or choose **Try sample voice**.
3. Choose **Review request**. Change the placement to left or right, or edit the instruction.
4. Choose **Arrange workspace**. Stop at any of the three stages, resume, or undo.
5. Open **Agents** to see the independent draggable/resizable monitor. Closing it does not stop work.

Keyboard: Ctrl+Space opens the composer; Enter submits the instruction; Shift+Enter inserts a newline; Escape stops running work or dismisses the composer/monitor; Ctrl/Cmd+Z undoes a layout change outside text inputs. All buttons are keyboard focusable.

## Honest boundaries

This is a simulated, bounded agent interaction. It does not call a model, access real files, or control the Linux VM. The window changes, partial results, interruption, resume, undo, and activity log are real browser state. Data is held only for this page session; refresh resets it. The document is a read-only example. Interpretation is deliberately limited to this arrangement task and should not be reused as the OS's intent router.

Sample voice plays a labelled transcript without opening the microphone. **Speak** uses browser SpeechRecognition if supported; the browser may use a remote recognition service. User permission is required. Unsupported browsers offer typing and sample voice. Live microphone capture was not tested during automated review.

The static clock belongs to the mock desktop scene. No token/model values are invented.

## Design choices

- Dark appearance only for this iteration.
- Opaque document surfaces and a raised instruction surface establish depth without pervasive glass or outlines.
- Selection outline identifies the object included in the request; it is not ornamental window chrome.
- The bar remains transparent: plain username left, plain Agents then date/time right, center empty, no dock.
- Locally bundled Commissioner; regular body text, medium headings, semibold primary actions.
- The composer is temporary. Completion becomes a compact receipt with Undo.
- Technical usage data lives in the independent monitor, not in the primary task flow.
- Layout adapts rather than scaling all text down. At narrow widths references stack below the note. Reduced motion is honored.

## Verification

Browser-inspected at the default desktop size and an 820×850 viewport. Verified review, correction to left, immediate stop, stop after references opened, resume to completion, undo restoring the original layout, sample transcript, missing-context feedback, unsupported-request feedback, and the separate monitor/history. `node --check app.js` passes. Live recognition, native compositor integration, screen-reader usability and complete accessibility conformance remain unverified.
