type CrawlWorkflowProps = {
  accountConnected: boolean
  workspaceConnected: boolean
  actionLabel: string
  actionDisabled: boolean
  onAction: () => void
}

export function CrawlWorkflow({
  accountConnected,
  workspaceConnected,
  actionLabel,
  actionDisabled,
  onAction,
}: CrawlWorkflowProps) {
  return (
    <section aria-labelledby="crawl-workflow-title" className="crawl-workflow">
      <div className="crawl-workflow__intro">
        <p className="section-kicker">WEBSITE OPERATIONS</p>
        <h2 id="crawl-workflow-title">Crawl verified websites</h2>
        <p>
          Run a bounded crawl, then review its findings and sitemap evidence.
          Crawling is enabled only after website ownership is verified.
        </p>
        <button
          className="button button--primary"
          disabled={actionDisabled}
          onClick={onAction}
          type="button"
        >
          {actionLabel}
        </button>
      </div>
      <ol className="crawl-workflow__steps">
        <li>
          <span className="crawl-workflow__number">01</span>
          <strong>Connect account</strong>
          <span>{accountConnected ? 'Signed in' : 'Sign-in required'}</span>
        </li>
        <li>
          <span className="crawl-workflow__number">02</span>
          <strong>Choose workspace</strong>
          <span>
            {workspaceConnected
              ? 'Workspace connected'
              : accountConnected
                ? 'Select an organization'
                : 'After sign-in'}
          </span>
        </li>
        <li>
          <span className="crawl-workflow__number">03</span>
          <strong>Verify, crawl, review</strong>
          <span>DNS check required before crawl</span>
        </li>
      </ol>
    </section>
  )
}
