import React from "react";
import { StatusBar } from "expo-status-bar";

import { CommandCenterScreen } from "./src/screens/CommandCenterScreen";

export default function App(): React.ReactElement {
  return (
    <>
      <StatusBar style="light" />
      <CommandCenterScreen />
    </>
  );
}
