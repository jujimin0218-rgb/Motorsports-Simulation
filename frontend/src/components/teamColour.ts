/**
 * A colour per team, stable for as long as the field is.
 *
 * Shared because a car has to be the same colour on the map, in the timing
 * tower and in a telemetry trace -- three places reading from two palettes is
 * how a car ends up blue in one panel and orange in the next.
 *
 * Stepped for this app's dark panel rather than picked by eye, and checked:
 * every adjacent pair clears the colour-blindness separation floor, none of
 * them reads grey, and all ten hold contrast against the surface.  The set the
 * screens used before failed that check -- four hues sat above the lightness
 * band and one was neutral enough to read as grey.
 *
 * Identity is never colour alone anyway: a car on the map carries its position,
 * a row in the tower carries the name, and a telemetry trace is labelled.
 */

const PALETTE = [
  '#3987e5', '#d95926', '#199e70', '#c98500', '#d55181',
  '#008300', '#9085e9', '#e66767', '#1295a6', '#7d9b2a',
]

/**
 * Assign colours by team id, sorted so the same field always gets the same
 * colours whichever order the rows happen to arrive in.
 */
export function teamColours(teamIds: Iterable<string>): (teamId: string) => string {
  const teams = [...new Set(teamIds)].sort()
  return (teamId: string) => PALETTE[Math.max(0, teams.indexOf(teamId)) % PALETTE.length]
}
