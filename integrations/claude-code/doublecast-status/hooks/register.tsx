import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Status } from '../types'

// Reads `doublecast status --json` (counts and masked samples only: no real value ever reaches
// this plugin) and shows it in the status line and in a "Doublecast" pane.

const PANE = 'doublecast'
const status = atom({ plugin: 'doublecast-status', key: 'status' } as const, null)
const error = atom({ plugin: 'doublecast-status', key: 'error' } as const, null)

const LABELS: Record<string, string> = {
  PERSON: 'people',
  ORG: 'companies',
  MONEY: 'amounts',
  EMAIL: 'emails',
  PHONE: 'phones',
}

async function poll($: EngineInterface): Promise<void> {
  try {
    const run = await $.process.run(['doublecast', 'status', '--json'])
    if (run.exitCode !== 0) {
      throw new Error(`exit ${run.exitCode}`)
    }
    const data = JSON.parse(run.stdout) as Status
    await update($, status, () => data)
    await update($, error, () => null)
    $.ui.status(`🛡 Doublecast ${data.proxy.running ? '●' : '○'} ${data.today_total} today`)
  } catch {
    await update($, error, () => 'Doublecast is not installed or not on PATH (pip install doublecast).')
    $.ui.status(undefined)
  }
}

async function clip($: EngineInterface, action: 'scramble' | 'restore'): Promise<void> {
  const run = await $.process.run(['doublecast', 'clip', action])
  $.ui.toast(run.exitCode === 0 ? `Clipboard ${action}d` : `Doublecast: clip ${action} failed`)
  await poll($)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'doublecast', description: 'Show what Doublecast protected today' })
    await poll($)
    $.clock.every(15000, () => poll($))

    return next(e)
  })

  on('command.run', { command: 'doublecast' }, async $ => {
    await poll($)
    await $.ui.open({ id: PANE, title: 'Doublecast' })

    return { text: 'Doublecast pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const data = await read($, status)
    const problem = await read($, error)

    if (problem || !data) {
      return (
        <Box flexDirection="column">
          <Text>{problem ?? 'Reading Doublecast…'}</Text>
        </Box>
      )
    }

    const today = Object.entries(data.today)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([cat, n]) => `${n} ${LABELS[cat] ?? cat.toLowerCase()}`)
      .join(' · ')

    return (
      <Box flexDirection="column">
        <Text bold>
          Doublecast {data.version} {data.proxy.running ? '● protecting this session' : '○ proxy off'}
        </Text>
        <Text>
          Today {data.today_total} swapped{today ? ` (${today})` : ''}
        </Text>
        <Text dimColor>Total {data.total_all} swapped · workspace {data.workspace}</Text>
        <Text> </Text>
        <Text bold>Last swaps</Text>
        {data.last.length === 0 && <Text dimColor>Nothing swapped yet.</Text>}
        {data.last.map(row => (
          <Text dimColor>
            {row.time} {row.category.toLowerCase()} {row.from} → {row.to} ({row.via})
          </Text>
        ))}
        <Text> </Text>
        <Box>
          <Button key="scramble" label="Scramble clipboard" hotkey="s" onPress={() => clip($, 'scramble')} />
          <Text> </Text>
          <Button key="restore" label="Restore clipboard" hotkey="r" onPress={() => clip($, 'restore')} />
          <Text> </Text>
          <Button key="refresh" label="Refresh" hotkey="u" onPress={() => poll($)} />
        </Box>
      </Box>
    )
  })
}
