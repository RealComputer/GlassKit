import { StatusBar } from "expo-status-bar";
import { SafeAreaView } from "react-native-safe-area-context";
import VoiceChatScreen from "../src/screens/VoiceChatScreen";

export default function Index() {
  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#111" }}
      edges={["top", "bottom"]}
    >
      <StatusBar style="light" />
      <VoiceChatScreen />
    </SafeAreaView>
  );
}
