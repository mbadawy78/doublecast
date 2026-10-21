export type Swap = { time: string; category: string; from: string; to: string; via: string }

export type Status = {
  version: string
  workspace: string
  proxy: { running: boolean; address: string }
  today: Record<string, number>
  today_total: number
  total_all: number
  last: Swap[]
}

declare module 'claude-code' {
  interface PluginState {
    'doublecast-status': { status: Status | null; error: string | null }
  }
}
