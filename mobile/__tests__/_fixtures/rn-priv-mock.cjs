
const React = require('react');
function passthrough(name){return function(p){return React.createElement(name, p, p && p.children);}}
module.exports = {
  View: passthrough('View'), Text: passthrough('Text'), ScrollView: passthrough('ScrollView'),
  TouchableOpacity: passthrough('TouchableOpacity'), ActivityIndicator: passthrough('ActivityIndicator'),
  StyleSheet: { create: (o) => o }, Linking: { openURL: async () => undefined },
  Platform: { OS: 'ios' },
};