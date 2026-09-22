import type { DailyScanResponse } from '../types'

interface ManualScanPanelProps {
  scan: DailyScanResponse | null
  isScanning: boolean
  onRun: () => void
  onSelectCandidate: (metric: string) => void
}

const displayMetric = (metric: string) => metric.replaceAll('_', ' ')

export const ManualScanPanel: React.FC<ManualScanPanelProps> = ({
  scan,
  isScanning,
  onRun,
  onSelectCandidate,
}) => {
  return (
    <section className="manual-scan-panel" aria-labelledby="manual-scan-title">
      <div className="manual-scan-heading">
        <div>
          <h2 id="manual-scan-title">Manual daily scan</h2>
          <p>Global semantic-metric screening. It creates candidates, not a driver, scope, or diagnosis.</p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={onRun} disabled={isScanning}>
          {isScanning ? 'Scanning declared metrics…' : 'Run daily scan'}
        </button>
      </div>

      {!scan && (
        <p className="manual-scan-empty">Run a scan to inspect the current global metric snapshot before starting an investigation.</p>
      )}

      {scan && (
        <div className="manual-scan-result">
          <div className="manual-scan-meta">
            <span>{scan.target_date}</span>
            <span>vs {scan.comparison}</span>
            <span>{scan.observations.length} declared metrics</span>
          </div>
          {scan.anomaly_candidate_metrics.length > 0 ? (
            <div className="candidate-row">
              <span className="candidate-label">Candidate metrics</span>
              <div className="candidate-actions">
                {scan.anomaly_candidate_metrics.map((metric) => (
                  <button
                    className="candidate-button"
                    key={metric}
                    type="button"
                    onClick={() => onSelectCandidate(metric)}
                  >
                    Investigate {displayMetric(metric)}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="manual-scan-clear">No anomalous global metric candidate was found for this date.</p>
          )}
          <p className="manual-scan-boundary">{scan.next_step}</p>
        </div>
      )}
    </section>
  )
}
