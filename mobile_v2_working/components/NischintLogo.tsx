import Svg, {
  Circle,
  Defs,
  G,
  LinearGradient,
  Path,
  Stop,
  SvgProps,
} from 'react-native-svg';

type NischintLogoProps = SvgProps & {
  size?: number;
};

export function NischintLogo({ size = 118, ...props }: NischintLogoProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 128 128" {...props}>
      <Defs>
        <LinearGradient id="shieldGradient" x1="18" y1="20" x2="112" y2="108" gradientUnits="userSpaceOnUse">
          <Stop offset="0" stopColor="#0EA5E9" />
          <Stop offset="0.48" stopColor="#0284C7" />
          <Stop offset="1" stopColor="#58E23C" />
        </LinearGradient>
        <LinearGradient id="shieldHighlight" x1="28" y1="16" x2="92" y2="54" gradientUnits="userSpaceOnUse">
          <Stop offset="0" stopColor="#7DD3FC" stopOpacity="0.5" />
          <Stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
        </LinearGradient>
      </Defs>

      <Path
        d="M64 9C52 15 38 19 22 23C20 59 30 91 64 112C98 91 108 59 106 23C90 19 76 15 64 9Z"
        fill="url(#shieldGradient)"
      />
      <Path
        d="M64 9C52 15 38 19 22 23C20 59 30 91 64 112C98 91 108 59 106 23C90 19 76 15 64 9Z"
        fill="url(#shieldHighlight)"
      />

      <G fill="#063B4F" opacity="0.82">
        <Circle cx="60" cy="40" r="14" />
        <Circle cx="62" cy="65" r="10.5" opacity="0.78" />
        <Path d="M27 79C40 99 68 106 91 82C72 92 51 91 34 75C31 73 28 76 27 79Z" />
        <Path d="M39 48C23 66 24 92 55 108C43 91 42 68 58 52C51 52 45 50 39 48Z" opacity="0.75" />
        <Path d="M77 58C95 71 95 94 69 108C82 90 79 75 63 66C68 65 73 62 77 58Z" opacity="0.68" />
        <Path d="M35 88C49 77 67 76 84 86C69 72 46 71 31 82C32 85 33 87 35 88Z" opacity="0.62" />
      </G>

      <Path
        d="M91 30L95 39L104 43L95 47L91 56L87 47L78 43L87 39L91 30Z"
        fill="#E6FFFA"
        opacity="0.74"
      />
    </Svg>
  );
}
