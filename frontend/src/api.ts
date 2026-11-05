export type Session = {code: string; token: string; role: 'student'|'instructor'}
const generations = new Map<string, number>()
export async function api<T>(path: string, session?: Session|null, body?: unknown): Promise<T> {
  const payload = body === undefined ? undefined : session ? {generation:generations.get(session.code)||0, ...body as object} : body
  const response = await fetch(`/api${path}`, {method: body === undefined ? 'GET' : 'POST', headers: {'Content-Type':'application/json', ...(session ? {Authorization:`Bearer ${session.token}`} : {})}, ...(body === undefined ? {} : {body: JSON.stringify(payload)})})
  if (!response.ok) {const data = await response.json().catch(()=>({})); throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check your input and try again.')}
  const result = await response.json()
  if (typeof result?.code === 'string' && typeof result?.generation === 'number') generations.set(result.code, Math.max(generations.get(result.code)||0, result.generation))
  return result
}
// randomUUID requires HTTPS in many browsers; getRandomValues also works on LAN HTTP.
export function requestId() { return Array.from(crypto.getRandomValues(new Uint8Array(16)), b=>b.toString(16).padStart(2,'0')).join('') }
