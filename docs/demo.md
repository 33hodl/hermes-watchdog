# Demo video — 52 seconds

Rules from the hackathon post: under 90 seconds, show the plugin working, tag
`@NousResearch`, and submit the link with the catalog PR.

This is the script for `hermes-watchdog-demo-v2.mp4` (52s, 1440x900). It is
customer-facing on purpose: the story is "your job failed and nobody told you",
not "here is a JSON payload".

## The story, in Command of the Message order

| part | what it says |
|---|---|
| before scenario | "3:07 am - nightly-report job failed. exit code 1. nobody saw it." |
| negative consequence | "four days later: the Monday deck is missing its numbers" |
| positive outcome | "fixed -> silence. not fixed -> the failure, the fix it tried, what's left for you" |
| required capability | "picks the fix that fits the failure, then checks whether the next run worked" |
| proof point | a real line from a live cycle: rerun_job -> next run succeeded -> recovered |
| differentiation | "a repair counts only when the next run succeeds, not when a retry was merely sent" |
| how to get it | `hermes plugins install hermes-watchdog` - free - no API keys |

## Narration

1. Your scheduled job failed at three in the morning. Nobody saw it. You found out four days later, when the numbers were already missing.
2. Watchdog notices. It picks a fix that matches the failure, and runs it: retry the job, restart what broke, or pause it so it stops burning the schedule.
3. Then it checks Hermes's own record to see whether the next run actually worked.
4. If it worked, you hear nothing at all. If it didn't, you get the failure, the fix it tried, and what's left for you to do.
5. A repair only counts when the next run succeeds. You're not trusting a retry that quietly failed again.
6. You stop being the retry button for your own automations. One command to install. Free, open source, no API keys. Links below.

Voice: Microsoft multilingual neural (`en-US-AvaMultilingualNeural`), the most
natural free option that needs no account. ElevenLabs free tier sounds better
still, but it needs the owner's account and API key (10k characters/month).

## How the file is made

`wd-video/build2.py` renders each beat as a card (headless Chrome screenshot of
plain-language text), then muxes the narration with ffmpeg. The technical line in
the "proof" card is copied from a real repair cycle on this machine, not invented.
It is not a screen capture of the Desktop app: the app runs on the owner's Mac and
the build host is a headless VPS.

## Assets

- video: `hermes-watchdog-demo-v2.mp4` (52s, 1440x900)
- narration: `audio-v2/s1..s6.mp3`
- scene text: `scenes2.json`

## Submission form

Needs: (1) catalog PR link, (2) demo video URL. Files due 5PM EST Nov 11
(06:00 SGT Nov 12).

- PR: https://github.com/NousResearch/hermes-agent/pull/149270
- Repo: https://github.com/33hodl/hermes-watchdog
- Seam request referenced in the PR: https://github.com/NousResearch/hermes-agent/issues/149262
