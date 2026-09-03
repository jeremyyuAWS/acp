import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Settings had TWO user tabs. "Users" rendered UserManagement.jsx: 293 lines of hardcoded
// SEED_USERS — real-looking names, emails, teams and roles — importing nothing from api.js, with
// no /users route behind it. "Test users" rendered AllowList, which is the actual access control.
//
// So the tab named Users was fiction, and the real one was named as though it were a testing
// convenience. Requirement 4/18c asked for "a list of users with access to ACP"; the product
// answered it with a mock next to the true answer.
//
// One tab now, backed by GET /admin/allowlist.
//
// AND THE REAL ONE WAS INCOMPLETE IN THE DANGEROUS DIRECTION. core.email_allowed() admits three
// ways — the owner, the list, or any address at an ACP_ALLOWED_DOMAINS domain. AllowList fetched
// `domains` into state and never rendered it. On a deployment with a domain configured, an entire
// company could sign in while this screen showed a handful of names and looked complete.
//
// Comment-stripped: this header names the deleted symbols, and a substring assertion would match
// the prose. That has bitten this repo three times.

const HERE = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

describe('the mock is gone', () => {
  it('UserManagement.jsx no longer exists', () => {
    expect(existsSync(join(HERE, 'UserManagement.jsx'))).toBe(false)
  })

  it('nothing imports or renders it', () => {
    const s = code('Settings.jsx')
    expect(s).not.toContain('UserManagement')
    expect(s, 'the seeded roster is back').not.toContain('SEED_USERS')
  })
})

describe('one Users tab, and it is the real one', () => {
  it('renders the unified People access experience', () => {
    expect(code('Settings.jsx')).toMatch(/\{tab === 'users' && <PeopleAccess \/>\}/)
    expect(code('Settings.jsx')).toMatch(/import PeopleAccess from '\.\/PeopleAccess\.jsx'/)
  })

  it('has no second user tab', () => {
    // Two tabs, one real and one not, is how the mock survived this long.
    const s = code('Settings.jsx')
    expect(s).not.toMatch(/tab === 'access'/)
    expect(s.match(/>Users</g) || [], 'more than one tab labelled Users').toHaveLength(1)
  })

  it('is backed by the allowlist endpoint, not local state', () => {
    const s = code('Settings.jsx')
    expect(s).toMatch(/getAllowlist\(\)/)
    expect(s).toMatch(/setAllowlist\(emails\)/)
  })
})

describe('the domain rule is visible', () => {
  it('renders the domains it fetches', () => {
    // THE defect. `domains` was loaded and dropped on the floor.
    const s = code('Settings.jsx')
    expect(s).toMatch(/domains\.length > 0 &&/)
    expect(s).toMatch(/domains\.map\(\(d\) =>/)
  })

  it('says these people are not in the list below', () => {
    // A domain grant admits someone who appears nowhere on this screen. Saying so is the whole
    // point — a list that looks complete and is not is worse than no list.
    const s = code('Settings.jsx')
    expect(s).toMatch(/can sign in without being listed below/)
    expect(s).toMatch(/ACP_ALLOWED_DOMAINS/)
  })

  it('states all three gates email_allowed() checks', () => {
    // It used to say "Two things let someone in" and name the list and Google test-user status —
    // omitting the owner and the domain, and asserting a Google prerequisite as if ACP checked it.
    const s = code('Settings.jsx')
    expect(s).toMatch(/What lets someone in/)
    expect(s).toMatch(/owner/)
    expect(s).toMatch(/allowed domain/)
    expect(s, 'the old two-gate claim is back').not.toMatch(/Two things let someone in/)
  })

  it('demotes the Google test-user step to what it is', () => {
    expect(code('Settings.jsx')).toMatch(/That is a Google requirement, not an ACP one/)
  })
})
