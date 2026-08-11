import { afterEach, describe, expect, it } from 'vitest'
import { scrollElementWithinMainContent } from './scroll'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('scrollElementWithinMainContent', () => {
  it('centers the target inside the app content scroller', () => {
    const container = document.createElement('main')
    const target = document.createElement('section')
    container.id = 'main-content'
    container.appendChild(target)
    document.body.appendChild(container)

    Object.defineProperties(container, {
      clientHeight: { configurable: true, value: 400 },
      scrollHeight: { configurable: true, value: 1200 },
    })
    container.scrollTop = 100
    container.getBoundingClientRect = () => ({ top: 50 } as DOMRect)
    target.getBoundingClientRect = () => ({ top: 650, height: 100 } as DOMRect)

    scrollElementWithinMainContent(target)

    expect(container.scrollTop).toBe(550)
  })

  it('clamps the requested position to the scrollable range', () => {
    const container = document.createElement('main')
    const target = document.createElement('section')
    container.id = 'main-content'
    container.appendChild(target)
    document.body.appendChild(container)

    Object.defineProperties(container, {
      clientHeight: { configurable: true, value: 400 },
      scrollHeight: { configurable: true, value: 600 },
    })
    container.getBoundingClientRect = () => ({ top: 0 } as DOMRect)
    target.getBoundingClientRect = () => ({ top: 900, height: 100 } as DOMRect)

    scrollElementWithinMainContent(target)

    expect(container.scrollTop).toBe(200)
  })
})
