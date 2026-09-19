import type { TSchema } from 'typebox';

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export const TOOL_NAMES = [
  'resolve_place', 'get_canal_access_options', 'find_hire_trip_options',
  'get_trip_option', 'search_amenities', 'request_selection',
] as const;
export type ToolName = typeof TOOL_NAMES[number];
export interface Limits {
  deadlineMs: number;
  maxModelCalls: number;
  maxToolCalls: number;
  maxOutputTokens: number;
  maxPayloadBytes: number;
  maxEvents: number;
}
export interface EventData {
  type: 'started' | 'text_delta' | 'tool_status' | 'options' | 'clarification'
    | 'browser_task' | 'complete' | 'error';
  data: Json;
}
export interface RunEvent extends EventData {
  sessionId: string;
  runId: string;
  revision: number;
  sequence: number;
}
export interface ToolContext {
  readonly ownerId: string;
  readonly sessionId: string;
  readonly runId: string;
  readonly revision: number;
  signal: AbortSignal;
  publish(type: 'options' | 'clarification', data: Json): void;
  requestBrowserTask(task: Json, responseSchema: TSchema): Promise<Json>;
}
export interface DomainTool {
  name: ToolName;
  description: string;
  parameters: TSchema;
  execute(args: unknown, context: ToolContext): Promise<Json>;
}
export interface BoundTool {
  name: ToolName;
  description: string;
  parameters: TSchema;
  execute(args: unknown): Promise<Json>;
}
export interface Driver {
  prompt(text: string): Promise<void>;
  abort(): Promise<void>;
  dispose(): void;
}
export interface DriverInput {
  tools: BoundTool[];
  limits: Limits;
  signal: AbortSignal;
  emit(event: EventData): void;
}
export type SessionFactory = (input: DriverInput) => Promise<Driver>;
export type ErrorCode = 'invalid_request' | 'not_found' | 'busy' | 'capacity'
  | 'stale_revision' | 'stale_result' | 'invalid_tool_arguments' | 'invalid_tool_surface'
  | 'limit_exceeded' | 'cancelled' | 'deadline_exceeded' | 'model_unavailable'
  | 'tool_failed' | 'internal_error';
export class AgentError extends Error {
  constructor(public readonly code: ErrorCode) { super(code); }
}
