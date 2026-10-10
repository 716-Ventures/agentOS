# Offline voice input

The terminal client and Linux voice service now support explicit, bounded microphone recording and local English speech recognition. This is an implemented input path, not acoustic or daily-use voice qualification.

In the dashboard, **V** starts recording, **V** finishes, and **V** opens the resulting editable transcript in its original tile. **Enter** submits the reviewed request. **Esc** discards recording or recognition. The dashboard shows recording, local transcription and transcript-ready states. Leaving closes the recorder; capture is capped at ten seconds and orphaned input processes are reaped. Keyboard, direct stop and the ordinary shell remain available.

Recording captures the activity ID, tile ID, job reference, layout revision, observation timestamp, displayed-output evidence and activity stop generation. Reviewing in another activity returns to the referenced tile only on the user's explicit V action. Closing that tile requires fresh input. Moving focus during recording does not retarget the request. Submitted context remains separately labeled untrusted evidence; it is not concatenated into the person's authorization. Stopping activity work after capture invalidates the pending request. A voice transcript never invokes the local approval shortcut.

`agent-os voice --file sample.wav` transcribes a 16 kHz mono, 16-bit PCM WAV of 0.25–10 seconds and prints the result for review. It does not submit a task. Very quiet input returns `no_signal` with no manufactured words. Background noise and recognition mistakes can still produce incorrect text; the editable review is intentional.

The separate unprivileged `agent-os-voice` service owns ALSA capture and a bounded CPU decoder. Linux peer credentials bind microphone sessions to the native input process. Other processes cannot finish its recording by copying the token. Service accounts cannot activate capture. The service has no network access or provider credentials. Audio and intermediate transcripts live in private temporary directories and are removed after recognition/cancellation. Reviewed request text and its context enter normal durable activity history.

`voice-assets.lock.json` pins whisper.cpp 1.9.5 source and tiny.en model revisions, byte lengths and SHA-256 hashes. `bootstrap_voice.py` builds the CPU decoder using authenticated Debian dependencies, verifies every asset, preserves upstream MIT notices and installs immutable content-addressed assets. Each runtime release records the exact asset descriptor; repeat installation reuses verified assets. Runtime startup verifies integrity before opening the service socket.

Verified in the ARM64 UTM guest: real offline decoding of the upstream ten-second speech fixture, zero-signal rejection, bounded formats, authenticated capture ownership, cancellation, no recorder leak, dashboard recording/review controls, no implicit request submission and stop-generation grounding validation. The decoder recognized the fixture in approximately 1.1 seconds in one run; this is not a latency distribution or an accuracy benchmark.

Still unqualified: intelligible speech arriving from the actual host microphone, speaker quality, varied accents/noise, end-to-end correction and p95 latency, screen-reader voice journeys and physical hardware. Earlier all-zero ALSA captures establish device plumbing only. The graphical launcher will use this same service and context contract.

The speech engine and weights retain MIT licensing; agentOS code remains Apache-2.0. See the installed asset directory's LICENSE files and NOTICE.
