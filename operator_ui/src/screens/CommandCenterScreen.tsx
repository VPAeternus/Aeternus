import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  SafeAreaView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View
} from "react-native";

import {
  createTriageIntent,
  fetchAllocatorReportCard,
  fetchAllocatorStatus,
  fetchBootstrap,
  fetchCandidateDetail
} from "../api/client";
import {
  AllocatorIntentDTO,
  AllocatorReportCardResponse,
  AllocatorStatusResponse,
  BootstrapResponse,
  CandidateDetailResponse,
  CandidateDTO,
  SnapshotEnvelope,
  TriageAction
} from "../api/types";
import { StatusPill } from "../components/StatusPill";

const POLL_MS = 15000;

function scheduleTone(status: string): "ok" | "warn" | "critical" | "muted" {
  const normalized = status.toUpperCase();
  if (normalized === "UNKNOWN") {
    return "critical";
  }
  if (normalized === "READY") {
    return "ok";
  }
  return "warn";
}

function snapshotTone(validity: string): "ok" | "warn" | "critical" | "muted" {
  if (validity === "VALID") {
    return "ok";
  }
  if (validity === "STALE") {
    return "warn";
  }
  return "critical";
}

function formatCountdown(secondsToNextRun: number | null): string {
  if (secondsToNextRun == null) {
    return "Unknown";
  }
  const safe = Math.max(0, Math.floor(secondsToNextRun));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

function allocatorStatusTone(status: string): "ok" | "warn" | "critical" | "muted" {
  const normalized = status.toUpperCase();
  if (normalized.startsWith("REJECTED_")) {
    return "critical";
  }
  if (normalized === "VALIDATED" || normalized === "FILLED") {
    return "ok";
  }
  if (normalized === "VALIDATED_WAIT_FUNDING" || normalized === "SUBMITTED") {
    return "warn";
  }
  return "muted";
}

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

interface CandidateRowProps {
  item: CandidateDTO;
  triageEnabled: boolean;
  submitKey: string;
  detailBusySymbol: string;
  selectedDetailSymbol: string;
  onAction: (action: TriageAction, candidate: CandidateDTO) => void;
  onApproveHint: () => void;
  onBlockHint: () => void;
  onInspect: (candidate: CandidateDTO) => void;
}

function CandidateRow({
  item,
  triageEnabled,
  submitKey,
  detailBusySymbol,
  selectedDetailSymbol,
  onAction,
  onApproveHint,
  onBlockHint,
  onInspect
}: CandidateRowProps): React.ReactElement {
  const laneTone = item.lane.toUpperCase().includes("MOMENTUM") ? "warn" : "ok";
  const approveBusy = submitKey === `${item.queue_id}:APPROVE`;
  const deferBusy = submitKey === `${item.queue_id}:DEFER`;
  const blockBusy = submitKey === `${item.queue_id}:BLOCK`;
  const inspectBusy = detailBusySymbol === item.symbol;
  const inspectSelected = selectedDetailSymbol === item.symbol;

  const buttonDisabled = (busy: boolean): boolean => !triageEnabled || busy;
  return (
    <View style={styles.candidateRow}>
      <View style={styles.candidateTop}>
        <Text style={styles.symbol}>{item.symbol}</Text>
        <Text style={styles.score}>{item.score}</Text>
      </View>
      <View style={styles.candidateMeta}>
        <StatusPill label={item.lane} tone={laneTone} />
        <StatusPill label={`C${item.confidence}`} tone="muted" />
        <StatusPill label={item.quality_tier} tone="muted" />
      </View>
      <Text numberOfLines={2} style={styles.thesis}>
        {item.thesis_summary}
      </Text>
      <View style={styles.actionRow}>
        <TouchableOpacity
          onPress={() => onInspect(item)}
          disabled={inspectBusy}
          style={[styles.actionBtn, styles.inspectBtn, inspectBusy && styles.actionBtnDisabled]}
        >
          <Text style={styles.actionBtnText}>{inspectBusy ? "..." : inspectSelected ? "Open" : "Inspect"}</Text>
        </TouchableOpacity>
        <Pressable
          onPress={() => onApproveHint()}
          onLongPress={() => onAction("APPROVE", item)}
          delayLongPress={1500}
          disabled={buttonDisabled(approveBusy)}
          style={({ pressed }) => [
            styles.actionBtn,
            styles.approveBtn,
            buttonDisabled(approveBusy) && styles.actionBtnDisabled,
            pressed && !buttonDisabled(approveBusy) && styles.actionBtnPressed
          ]}
        >
          <Text style={styles.actionBtnText}>{approveBusy ? "..." : "Approve (hold)"}</Text>
        </Pressable>
        <TouchableOpacity
          onPress={() => onAction("DEFER", item)}
          disabled={buttonDisabled(deferBusy)}
          style={[styles.actionBtn, styles.deferBtn, buttonDisabled(deferBusy) && styles.actionBtnDisabled]}
        >
          <Text style={styles.actionBtnText}>{deferBusy ? "..." : "Defer"}</Text>
        </TouchableOpacity>
        <Pressable
          onPress={() => onBlockHint()}
          onLongPress={() => onAction("BLOCK", item)}
          delayLongPress={1200}
          disabled={buttonDisabled(blockBusy)}
          style={({ pressed }) => [
            styles.actionBtn,
            styles.blockBtn,
            buttonDisabled(blockBusy) && styles.actionBtnDisabled,
            pressed && !buttonDisabled(blockBusy) && styles.actionBtnPressed
          ]}
        >
          <Text style={styles.actionBtnText}>{blockBusy ? "..." : "Block (hold)"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

export function CommandCenterScreen(): React.ReactElement {
  const [bootstrap, setBootstrap] = useState<BootstrapResponse | null>(null);
  const [allocatorStatus, setAllocatorStatus] = useState<AllocatorStatusResponse | null>(null);
  const [allocatorReport, setAllocatorReport] = useState<AllocatorReportCardResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [actionMessage, setActionMessage] = useState<string>("");
  const [submitKey, setSubmitKey] = useState<string>("");
  const [detailBusySymbol, setDetailBusySymbol] = useState<string>("");
  const [detail, setDetail] = useState<CandidateDetailResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  const load = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const [bootstrapPayload, allocatorStatusPayload, allocatorReportPayload] = await Promise.all([
        fetchBootstrap(),
        fetchAllocatorStatus(120),
        fetchAllocatorReportCard(7)
      ]);
      setBootstrap(bootstrapPayload);
      setAllocatorStatus(allocatorStatusPayload);
      setAllocatorReport(allocatorReportPayload);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load command center");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(false).catch(() => undefined);
    const timer = setInterval(() => {
      load(false).catch(() => undefined);
    }, POLL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [load]);

  const blockingAlerts = useMemo(
    () => (bootstrap?.alerts ?? []).filter((row) => row.blocking),
    [bootstrap]
  );
  const triageEnabled = useMemo(
    () => Boolean(bootstrap?.snapshot.triage_enabled) && blockingAlerts.length === 0,
    [bootstrap?.snapshot.triage_enabled, blockingAlerts.length]
  );
  const recentAllocatorRows = useMemo(
    () => (allocatorStatus?.items ?? []).slice(0, 5),
    [allocatorStatus?.items]
  );

  const onAction = useCallback(
    async (action: TriageAction, candidate: CandidateDTO) => {
      if (!bootstrap) {
        return;
      }
      if (!triageEnabled) {
        setActionMessage("Triage disabled by current safety state.");
        return;
      }
      setSubmitKey(`${candidate.queue_id}:${action}`);
      setActionMessage("");
      try {
        const snapshot: SnapshotEnvelope = bootstrap.snapshot;
        const result = await createTriageIntent({
          action,
          symbol: candidate.symbol,
          queue_id: candidate.queue_id,
          target_queue_run_id: bootstrap.schedule.queue_run_id_target,
          snapshot_id: snapshot.snapshot_id,
          snapshot_hash_canonical: snapshot.snapshot_hash_canonical,
          snapshot_hash_raw: snapshot.snapshot_hash_raw,
          snapshot_validity: snapshot.validity,
          thesis_tags: [candidate.research_playbook.toLowerCase()],
          operator_note: `operator_ui:${action.toLowerCase()}`,
          created_by: "operator-ui"
        });
        setActionMessage(
          `${result.action} accepted for ${result.symbol} (${result.intent_id.slice(0, 8)}...)`
        );
        await load(false);
      } catch (err) {
        setActionMessage(err instanceof Error ? err.message : "Action failed");
      } finally {
        setSubmitKey("");
      }
    },
    [bootstrap, triageEnabled, load]
  );

  const onInspect = useCallback(async (candidate: CandidateDTO) => {
    setDetailBusySymbol(candidate.symbol);
    try {
      const payload = await fetchCandidateDetail(candidate.symbol);
      setDetail(payload);
      setActionMessage("");
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Failed to load candidate detail");
    } finally {
      setDetailBusySymbol("");
    }
  }, []);

  const onApproveHint = useCallback(() => {
    if (!triageEnabled) {
      return;
    }
    setActionMessage("Hold Approve for 1.5s to submit intent.");
  }, [triageEnabled]);

  const onBlockHint = useCallback(() => {
    if (!triageEnabled) {
      return;
    }
    setActionMessage("Hold Block for 1.2s to submit constraint intent.");
  }, [triageEnabled]);

  if (loading && !bootstrap) {
    return (
      <SafeAreaView style={styles.rootLoading}>
        <ActivityIndicator size="large" color="#9ac1ff" />
        <Text style={styles.loadingText}>Loading Aeternus command center...</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.title}>Aeternus Operator</Text>
        <TouchableOpacity onPress={() => load(true)} style={styles.refreshBtn}>
          <Text style={styles.refreshText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {actionMessage ? <Text style={styles.actionMessage}>{actionMessage}</Text> : null}

      {bootstrap ? (
        <View style={styles.kpiRow}>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Schedule</Text>
            <StatusPill label={bootstrap.schedule.schedule_status} tone={scheduleTone(bootstrap.schedule.schedule_status)} />
            <Text style={styles.kpiValue}>T- {formatCountdown(bootstrap.schedule.seconds_to_next_run)}</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Snapshot</Text>
            <StatusPill label={bootstrap.snapshot.validity} tone={snapshotTone(bootstrap.snapshot.validity)} />
            <Text style={styles.kpiValue}>{bootstrap.summary.total_candidates} candidates</Text>
          </View>
          <View style={styles.kpiCard}>
            <Text style={styles.kpiLabel}>Funding</Text>
            <StatusPill
              label={bootstrap.allocator_pending_funding_count > 0 ? "PENDING" : "CLEAR"}
              tone={bootstrap.allocator_pending_funding_count > 0 ? "warn" : "ok"}
            />
            <Text style={styles.kpiValue}>
              {bootstrap.allocator_pending_funding_count} waiting / {bootstrap.allocator_pending_count} open
            </Text>
          </View>
        </View>
      ) : null}

      {blockingAlerts.length > 0 ? (
        <View style={styles.alertBox}>
          <Text style={styles.alertTitle}>Blocking Alerts</Text>
          {blockingAlerts.map((alert) => (
            <Text key={alert.code} style={styles.alertLine}>
              {alert.code}: {alert.message}
            </Text>
          ))}
        </View>
      ) : null}

      {bootstrap && bootstrap.allocator_pending_funding_count > 0 ? (
        <View style={styles.infoBox}>
          <Text style={styles.infoTitle}>Settlement Queue</Text>
          <Text style={styles.infoLine}>
            {bootstrap.allocator_pending_funding_count} intent(s) are waiting on settlement or funding release.
          </Text>
        </View>
      ) : null}

      {allocatorReport ? (
        <View style={styles.vetoBox}>
          <View style={styles.vetoHeader}>
            <Text style={styles.vetoTitle}>Veto Dashboard (7d)</Text>
            <StatusPill
              label={allocatorReport.rejected_count > 0 ? "ACTIVE" : "QUIET"}
              tone={allocatorReport.rejected_count > 0 ? "warn" : "ok"}
            />
          </View>
          <Text style={styles.vetoLine}>
            Intents: {allocatorReport.total_intents} | Validated: {formatPercent(allocatorReport.validation_rate_pct)} |
            Vetoed: {formatPercent(allocatorReport.veto_rate_pct)}
          </Text>
          <Text style={styles.vetoLine}>
            Pending funding: {allocatorReport.pending_funding_count} | Pending total: {allocatorReport.pending_count}
          </Text>
          {(allocatorReport.rejection_reason_counts ?? []).slice(0, 3).map((row) => (
            <Text key={row.reason_code} style={styles.vetoReason}>
              {row.reason_code}: {row.count}
            </Text>
          ))}
        </View>
      ) : null}

      {recentAllocatorRows.length > 0 ? (
        <View style={styles.intentTableBox}>
          <Text style={styles.intentTableTitle}>Recent Allocator Intents</Text>
          {recentAllocatorRows.map((row: AllocatorIntentDTO) => (
            <View key={row.intent_id} style={styles.intentRow}>
              <Text style={styles.intentSymbol}>{row.symbol}</Text>
              <StatusPill label={row.status} tone={allocatorStatusTone(row.status)} />
              <Text style={styles.intentFunding}>
                {row.funding_source_status || "UNFUNDED"}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {detail ? (
        <View style={styles.detailBox}>
          <Text style={styles.detailTitle}>{detail.candidate.symbol} Deep Dive</Text>
          <Text style={styles.detailLine}>
            Recommendation: {String(detail.analysis.recommendation ?? "Data Unavailable")}
          </Text>
          <Text style={styles.detailLine}>
            Rating: {String(detail.analysis.rating ?? "Data Unavailable")}
          </Text>
          <Text style={styles.detailLine}>
            Score: {String(detail.analysis.aeternus_score ?? "Data Unavailable")}
          </Text>
          <Text style={styles.detailLine}>
            Snapshot: {detail.snapshot.validity} / {detail.snapshot.as_of_date}
          </Text>
        </View>
      ) : null}

      <FlatList
        data={bootstrap?.top_candidates ?? []}
        keyExtractor={(item) => item.queue_id}
        renderItem={({ item }) => (
          <CandidateRow
            item={item}
            triageEnabled={triageEnabled}
            submitKey={submitKey}
            detailBusySymbol={detailBusySymbol}
            selectedDetailSymbol={detail?.candidate.symbol ?? ""}
            onAction={onAction}
            onApproveHint={onApproveHint}
            onBlockHint={onBlockHint}
            onInspect={onInspect}
          />
        )}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor="#9ac1ff" />}
        ListEmptyComponent={<Text style={styles.empty}>No candidates available.</Text>}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#111722"
  },
  rootLoading: {
    flex: 1,
    backgroundColor: "#111722",
    justifyContent: "center",
    alignItems: "center"
  },
  loadingText: {
    color: "#f8f6f2",
    marginTop: 12
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12
  },
  title: {
    color: "#f8f6f2",
    fontSize: 26,
    fontWeight: "800",
    letterSpacing: 0.4
  },
  refreshBtn: {
    backgroundColor: "#223042",
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8
  },
  refreshText: {
    color: "#f8f6f2",
    fontWeight: "700"
  },
  error: {
    color: "#ff9f9f",
    paddingHorizontal: 16,
    marginBottom: 8
  },
  actionMessage: {
    color: "#b6d8ff",
    paddingHorizontal: 16,
    marginBottom: 8
  },
  kpiRow: {
    flexDirection: "row",
    gap: 10,
    paddingHorizontal: 16,
    marginBottom: 10
  },
  kpiCard: {
    flex: 1,
    backgroundColor: "#1a2534",
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#2a3a52"
  },
  kpiLabel: {
    color: "#9cb4d8",
    fontWeight: "600",
    marginBottom: 8
  },
  kpiValue: {
    color: "#f8f6f2",
    marginTop: 8,
    fontSize: 13
  },
  alertBox: {
    backgroundColor: "#3a2226",
    borderColor: "#8b3f47",
    borderWidth: 1,
    borderRadius: 10,
    marginHorizontal: 16,
    marginBottom: 10,
    padding: 10
  },
  alertTitle: {
    color: "#ffd8dc",
    fontWeight: "700",
    marginBottom: 4
  },
  alertLine: {
    color: "#ffd8dc",
    fontSize: 12,
    marginTop: 2
  },
  infoBox: {
    backgroundColor: "#1d2a3a",
    borderColor: "#35506f",
    borderWidth: 1,
    borderRadius: 10,
    marginHorizontal: 16,
    marginBottom: 10,
    padding: 10
  },
  infoTitle: {
    color: "#c8ddff",
    fontWeight: "700",
    marginBottom: 4
  },
  infoLine: {
    color: "#c8ddff",
    fontSize: 12
  },
  vetoBox: {
    backgroundColor: "#1e2237",
    borderColor: "#3f4c79",
    borderWidth: 1,
    borderRadius: 10,
    marginHorizontal: 16,
    marginBottom: 10,
    padding: 10,
    gap: 4
  },
  vetoHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  vetoTitle: {
    color: "#d6def6",
    fontWeight: "800"
  },
  vetoLine: {
    color: "#c9d4ef",
    fontSize: 12
  },
  vetoReason: {
    color: "#f0b9c4",
    fontSize: 12
  },
  intentTableBox: {
    backgroundColor: "#1a2030",
    borderColor: "#39435d",
    borderWidth: 1,
    borderRadius: 10,
    marginHorizontal: 16,
    marginBottom: 10,
    padding: 10,
    gap: 6
  },
  intentTableTitle: {
    color: "#d9e2f8",
    fontWeight: "700"
  },
  intentRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8
  },
  intentSymbol: {
    color: "#f8f6f2",
    width: 52,
    fontWeight: "700"
  },
  intentFunding: {
    color: "#9fb3d7",
    fontSize: 11,
    flex: 1
  },
  list: {
    paddingHorizontal: 16,
    paddingBottom: 20,
    gap: 10
  },
  candidateRow: {
    backgroundColor: "#182133",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#2c3d57",
    padding: 12,
    gap: 8
  },
  candidateTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  symbol: {
    color: "#f8f6f2",
    fontWeight: "800",
    fontSize: 18
  },
  score: {
    color: "#b6d8ff",
    fontWeight: "800",
    fontSize: 16
  },
  candidateMeta: {
    flexDirection: "row",
    gap: 8,
    flexWrap: "wrap"
  },
  thesis: {
    color: "#d8dfeb",
    fontSize: 13,
    lineHeight: 18
  },
  actionRow: {
    flexDirection: "row",
    gap: 8
  },
  actionBtn: {
    flex: 1,
    borderRadius: 8,
    paddingVertical: 8,
    alignItems: "center"
  },
  approveBtn: {
    backgroundColor: "#1f7a4f"
  },
  deferBtn: {
    backgroundColor: "#6b5f32"
  },
  blockBtn: {
    backgroundColor: "#7a2f3a"
  },
  inspectBtn: {
    backgroundColor: "#2b3a52"
  },
  actionBtnDisabled: {
    opacity: 0.4
  },
  actionBtnPressed: {
    transform: [{ scale: 0.98 }]
  },
  actionBtnText: {
    color: "#f8f6f2",
    fontWeight: "700",
    fontSize: 12
  },
  detailBox: {
    backgroundColor: "#1b2740",
    borderColor: "#31486e",
    borderWidth: 1,
    borderRadius: 10,
    marginHorizontal: 16,
    marginBottom: 10,
    padding: 10,
    gap: 4
  },
  detailTitle: {
    color: "#cfe0ff",
    fontWeight: "800",
    marginBottom: 2
  },
  detailLine: {
    color: "#dbe5f7",
    fontSize: 12
  },
  empty: {
    color: "#9cb4d8",
    textAlign: "center",
    paddingTop: 24
  }
});
