
const React = require('react');
function p(name){return function(props){return React.createElement(name, props, props && props.children);}}
const Svg = p('Svg');
Svg.Circle = p('Circle'); Svg.Line = p('Line'); Svg.Path = p('Path'); Svg.Text = p('SvgText');
module.exports = { default: Svg, Circle: p('Circle'), Line: p('Line'),
                   Path: p('Path'), Text: p('SvgText') };