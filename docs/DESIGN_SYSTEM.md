# EdgeIQ Design System

EdgeIQ is a mission-control workspace for sports research, not a sportsbook slip. Calm surfaces put the decision and its uncertainty ahead of decoration.

## Color

Shared tokens live in `web/static/styles.css`. Graphite backgrounds and charcoal surfaces carry most of the interface. `--brand-accent` marks the active destination and primary action; it should not decorate every card. Green means favorable or verified, amber means caution or aging evidence, red means invalid or failed, blue means neutral research, and gray means supporting metadata. Every semantic color must be paired with a text label.

## Type and Numbers

Page title, section title, player or game name, primary metric, then metadata form the scanning order. Use tabular numerals and precision appropriate to the stat. A calibrated probability is the primary percentage only when a nonempty settled sample is available; otherwise label the number **Model probability**. Do not turn an unavailable market price into an implied probability.

## Space and Surfaces

Use the shared 4/8/12/16/24 px spacing scale and 4/6/8 px radii. Sections are unframed or use one subtle panel border; avoid nested decorative cards. Tables may scroll horizontally on narrow screens, while recommendation cards should stack their details.

## Actions and Status

Primary buttons are reserved for one clear action. Secondary buttons handle inspection and routine commands. Destructive actions retain red text or border treatment. Loading states acknowledge work in progress; disabled actions remain readable and explain why through adjacent text. Focus outlines must remain visible by keyboard.

Use the same words across screens: Fresh, Aging, Stale, Expired, Verified, Unverified, Calibrated, Partial, Insufficient Sample, Healthy, Degraded, and Unavailable. Do not equate freshness with statistical validation.

## Recommendation Cards

The first layer shows player, stat, direction, exact line, qualified probability, grade, fragility, and evidence state. EdgeIQ Score remains separate from probability. Only a `CALIBRATED` estimate receives the calibrated label; partial or degraded adjustments are labeled provisional, and insufficient-history estimates are labeled capped. Raw model probability stays in supporting context when it differs from the decision-facing value. The comparison track appears only when an exact-line market probability exists. Projection and model probability are secondary; supporting factors and equally visible counterarguments open below. Evidence and advanced diagnostics remain progressively disclosed.

## Charts and Motion

Use compact lines, range bands, or comparison tracks only when they answer a decision question. The expected-range band shows the model's 25th and 75th percentiles, with distinct projection and market-line markers; hide it when the distribution is incomplete or invalid. Market and model values need labels and sample context. Avoid radar charts, decorative 3D, continuous glows, and flashing numbers. Respect `prefers-reduced-motion`.

## Responsive and Accessible

The mobile bottom navigation exposes five intent-based destinations. Games and Best Lines remain reachable through More. Touch targets should be at least 42 px high, text must wrap without clipping, and primary commands must remain reachable. New controls require semantic labels, keyboard operation, and contrast against the dark surface.

Ask EdgeIQ places the question before its Research action and answer. Live-entry progress and trending games remain available under Other live context rather than competing with the question on a narrow screen.
