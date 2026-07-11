
module.exports = { useRouter: () => ({ back: () => undefined, push: () => undefined }),
                   useLocalSearchParams: () => ({ userId: 'u1' }),
                   router: { push: () => undefined } };