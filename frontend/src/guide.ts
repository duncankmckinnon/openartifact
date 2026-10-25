/** A computed style guide measured from the same page renderer and selectors as real artifacts. */
import { buildPage } from './page.ts'
import { splitPages } from './split.ts'
import type { ArtifactConfig, ArtifactData, ArtifactType } from './types.ts'

const TYPES: ArtifactType[] = ['deck', 'document', 'page']
export const LEVELS = ['Title', 'Heading 1', 'Heading 2', 'Heading 3', 'Body', 'Small', 'Code'] as const
export const GUIDE_TOKENS: Array<[string, string]> = [
  ['--slide-bg', 'Background'],
  ['--surface', 'Surface'],
  ['--slide-text', 'Text'],
  ['--slide-heading', 'Headings'],
  ['--accent', 'Accent'],
  ['--accent-secondary', 'Accent 2'],
  ['--accent-tertiary', 'Accent 3'],
  ['--color-muted', 'Muted'],
]
const SPECIMEN = `<!-- class: cover -->

# Annual report

---

# Where we are

## Revenue by region

### Key figures

Steady growth across every market we serve. <small>Source: internal finance</small>

\`\`\`js
revenue.by('region')
\`\`\`
`

export function guideRequested(): boolean {
  return new URLSearchParams(location.search).has('guide')
}

export function guideType(fallback: ArtifactType): ArtifactType {
  const requested = new URLSearchParams(location.search).get('type')
  return TYPES.find((type) => type === requested) ?? fallback
}

export function guidePage(type: ArtifactType): number {
  return TYPES.indexOf(type) + 1
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  node.className = cls
  if (text) node.textContent = text
  return node
}

function rounded(value: string): string {
  return value.replace(/-?\d+\.\d+px/g, (part) => `${Math.round(Number.parseFloat(part) * 10) / 10}px`)
}

function hex(value: string): string {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 1
  const ctx = canvas.getContext('2d')
  if (!ctx) return value
  ctx.fillStyle = value
  ctx.fillRect(0, 0, 1, 1)
  const channels = [...ctx.getImageData(0, 0, 1, 1).data]
  return `#${channels
    .slice(0, channels[3] === 255 ? 3 : 4)
    .map((v) => v.toString(16).padStart(2, '0'))
    .join('')}`
}

export function renderGuide(root: HTMLElement, data: ArtifactData, config: ArtifactConfig): void {
  const guide = element('div', `oa-guide theme-${config.theme}`)
  guide.dataset.type = config.type
  const header = element('header', 'oa-guide-header')
  header.append(element('h1', '', config.title || 'Style guide'))
  const nav = element('nav', 'oa-guide-types')
  nav.setAttribute('aria-label', 'Artifact type')
  for (const type of TYPES) {
    const link = element('a', '', type[0].toUpperCase() + type.slice(1))
    const url = new URL(location.href)
    url.searchParams.set('guide', '')
    url.searchParams.set('type', type)
    link.href = url.pathname + url.search + url.hash
    link.dataset.type = type
    if (type === config.type) link.setAttribute('aria-current', 'page')
    nav.append(link)
  }
  header.append(nav)
  guide.append(header)

  const specimen = element('div', 'oa-guide-specimen')
  specimen.setAttribute('aria-hidden', 'true')
  const wrapper = element(
    'div',
    `artifact artifact-${config.type} theme-${config.theme}${config.type === 'deck' ? ' deck-presenter' : ''}`,
  )
  const stream = config.type === 'deck' ? element('div', 'deck') : wrapper
  if (stream !== wrapper) wrapper.append(stream)
  const specimenConfig = { ...config, page_component: undefined }
  const pages = splitPages(SPECIMEN).map((page, i) => buildPage(page, i, 2, data, specimenConfig))
  for (const page of pages) page.classList.add('page--active')
  stream.append(...pages)
  specimen.append(wrapper)
  root.replaceChildren(guide, specimen)

  guide.append(element('h2', '', 'Colour scheme'))
  const colors = element('div', 'oa-guide-colors')
  const probe = element('span', '')
  const tokenRoot = pages[1].querySelector('.page-body') ?? pages[1]
  tokenRoot.append(probe)
  for (const [token, label] of GUIDE_TOKENS) {
    if (!getComputedStyle(tokenRoot).getPropertyValue(token).trim()) continue
    probe.style.color = `var(${token})`
    const value = hex(getComputedStyle(probe).color)
    const swatch = element('div', 'oa-guide-color')
    swatch.dataset.token = token
    swatch.dataset.value = value
    const chip = element('span', 'oa-guide-swatch')
    chip.style.backgroundColor = value
    swatch.append(chip, element('strong', '', label), element('code', '', value))
    colors.append(swatch)
  }
  guide.append(colors, element('h2', '', 'Fonts'))
  const fonts = element('div', 'oa-guide-fonts')
  for (const [role, token] of [
    ['heading', '--font-heading'],
    ['body', '--font-body'],
    ['mono', '--font-mono'],
  ]) {
    probe.style.fontFamily = `var(${token})`
    const family = getComputedStyle(probe)
      .fontFamily.split(',')[0]
      .trim()
      .replace(/^['"]|['"]$/g, '')
    const font = element('div', 'oa-guide-font', `${role}: ${family}`)
    font.dataset.role = role
    font.dataset.family = family
    font.style.fontFamily = getComputedStyle(probe).fontFamily
    fonts.append(font)
  }
  guide.append(fonts, element('p', 'oa-guide-note', 'Font families defined by this style.'))
  guide.append(element('h2', '', 'Type scale'))
  const table = element('table', 'oa-guide-levels')
  const tbody = element('tbody', '')
  const selectors = ['h1', 'h1', 'h2', 'h3', 'p', 'small', 'pre code']
  for (const [i, level] of LEVELS.entries()) {
    const source = pages[i === 0 ? 0 : 1].querySelector<HTMLElement>(selectors[i])
    if (!source) continue
    const style = getComputedStyle(source)
    const row = element('tr', 'oa-guide-level')
    row.dataset.level = level
    row.dataset.size = rounded(style.fontSize)
    row.dataset.lineHeight = rounded(style.lineHeight)
    row.dataset.weight = style.fontWeight
    const label = element('th', '', level)
    label.scope = 'row'
    const cell = element('td', '')
    const sample = element(
      'span',
      'oa-guide-sample',
      (i === 4 ? source.firstChild?.textContent?.trim() : source.textContent) || level,
    )
    for (const property of [
      'font-family',
      'font-size',
      'line-height',
      'font-weight',
      'font-style',
      'letter-spacing',
      'text-transform',
      'color',
      'font-variant',
      'text-decoration',
    ]) {
      sample.style.setProperty(property, style.getPropertyValue(property))
    }
    sample.style.setProperty('white-space', 'normal')
    const details = `${row.dataset.size} / ${row.dataset.lineHeight} · ${row.dataset.weight}${style.textTransform === 'uppercase' ? ' · caps' : ''}${style.letterSpacing !== 'normal' ? ` · ${rounded(style.letterSpacing)}` : ''}`
    cell.append(sample, element('div', 'oa-guide-metrics', details))
    row.append(label, cell)
    tbody.append(row)
  }
  table.append(tbody)
  guide.append(table)
  document.title = `${config.title || 'Style'} - Style guide`
}
