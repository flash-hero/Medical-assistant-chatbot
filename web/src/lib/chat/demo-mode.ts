/**
 * Whether the chat shows the demo banner.
 *
 * `sessionDemoMode` is null until POST /session answers (or when it failed). Unknown counts as demo,
 * the API client's own default for a missing `demo_mode`: the warning is in the server-rendered page
 * instead of appearing after the session request and pushing the conversation down (layout shift).
 * A turn's meta event can switch demo on, never off.
 */
export function isDemoMode(sessionDemoMode: boolean | null, turnDemoMode: boolean | null): boolean {
  return sessionDemoMode !== false || turnDemoMode === true;
}
