export function scrollElementWithinMainContent(target: HTMLElement | null) {
  const container = document.getElementById('main-content')
  if (!target || !container) return

  const containerRect = container.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  const targetTop = container.scrollTop + targetRect.top - containerRect.top
  const centeredTop = targetTop - (container.clientHeight - targetRect.height) / 2
  const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight)

  container.scrollTop = Math.min(maxScrollTop, Math.max(0, centeredTop))
}
