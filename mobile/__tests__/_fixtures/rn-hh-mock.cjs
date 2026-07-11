
const React = require('react');
function p(name){return function(props){return React.createElement(name, props, props && props.children);}}
module.exports = {
  View: p('View'), Text: p('Text'), ScrollView: p('ScrollView'),
  TouchableOpacity: p('TouchableOpacity'), ActivityIndicator: p('ActivityIndicator'),
  StyleSheet: { create: (o) => o },
  Dimensions: { get: () => ({ width: 360, height: 800 }) },
};