import React from "react";
import { StyleSheet, Text, View } from "react-native";

interface StatusPillProps {
  label: string;
  tone: "ok" | "warn" | "critical" | "muted";
}

const toneColors: Record<StatusPillProps["tone"], string> = {
  ok: "#1f9d61",
  warn: "#b8892d",
  critical: "#c13f3f",
  muted: "#4a5768"
};

export function StatusPill({ label, tone }: StatusPillProps): React.ReactElement {
  return (
    <View style={[styles.pill, { backgroundColor: toneColors[tone] }]}>
      <Text style={styles.label}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: "flex-start"
  },
  label: {
    color: "#f8f6f2",
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.4
  }
});
