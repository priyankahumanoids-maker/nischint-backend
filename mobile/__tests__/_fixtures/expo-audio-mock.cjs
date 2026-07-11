module.exports = {
  AudioModule: {
    requestRecordingPermissionsAsync: async () => ({ granted: true }),
    AudioRecorder: function () {
      this.uri = 'mock://audio.m4a';
      this.prepareToRecordAsync = async () => undefined;
      this.record = () => undefined;
      this.stop = async () => undefined;
      this.getStatus = () => ({ isRecording: false, metering: -30 });
    },
  },
  RecordingPresets: { HIGH_QUALITY: {} },
};