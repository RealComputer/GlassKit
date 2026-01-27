import { useRef, useState } from "react";
import { Modal, View, TouchableOpacity, Text } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { manipulateAsync, SaveFormat } from "expo-image-manipulator";

type CameraModalProps = {
  visible: boolean;
  onClose: () => void;
  onShot: (base64: string) => void;
};

export default function CameraModal({
  visible,
  onClose,
  onShot,
}: CameraModalProps) {
  const cameraRef = useRef<CameraView>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);

  if (!permission?.granted) {
    return (
      <Modal visible={visible} transparent animationType="fade">
        <View
          style={{
            flex: 1,
            backgroundColor: "#000c",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            paddingHorizontal: 24,
          }}
        >
          <TouchableOpacity
            onPress={requestPermission}
            style={{ padding: 16, backgroundColor: "#fff", borderRadius: 8 }}
          >
            <Text style={{ fontWeight: "600" }}>Grant camera permission</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onClose}
            style={{ padding: 12, backgroundColor: "#ddd", borderRadius: 8 }}
          >
            <Text>Cancel</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    );
  }

  return (
    <Modal visible={visible} animationType="slide">
      <View style={{ flex: 1, backgroundColor: "black" }}>
        <CameraView
          ref={cameraRef}
          style={{ flex: 1 }}
          facing="back"
          onCameraReady={() => setReady(true)}
        />
        <View
          style={{
            position: "absolute",
            bottom: 48,
            width: "100%",
            alignItems: "center",
            gap: 16,
          }}
        >
          <TouchableOpacity
            onPress={async () => {
              if (!cameraRef.current || !ready) return;
              const shot = await cameraRef.current.takePictureAsync();
              const result = await manipulateAsync(
                shot.uri,
                [{ resize: { height: 1000 } }],
                { base64: true, compress: 0.5, format: SaveFormat.JPEG },
              );
              const b64 = result.base64;
              if (b64) {
                onShot(b64);
              }
              onClose();
            }}
            style={{
              width: 88,
              height: 88,
              borderRadius: 44,
              backgroundColor: "#fff",
            }}
          />
          <TouchableOpacity onPress={onClose}>
            <Text style={{ color: "white", fontSize: 16 }}>Close</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}
