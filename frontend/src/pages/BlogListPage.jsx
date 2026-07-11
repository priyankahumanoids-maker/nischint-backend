import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Shield, Clock, Eye, ChevronRight, Search, Loader2 } from 'lucide-react';
import { cleanGet } from '../lib/cleanFetch';

const API = '';  // same-origin — no CORS, no stale baked-URL risk

const CAT_META = {
  women_safety: { label: 'Women Safety', color: '#ec4899', bg: 'bg-pink-500/15 text-pink-400' },
  child_safety: { label: 'Child Safety', color: '#f59e0b', bg: 'bg-amber-500/15 text-amber-400' },
  family_safety: { label: 'Family Safety', color: '#10b981', bg: 'bg-emerald-500/15 text-emerald-400' },
  product: { label: 'Product', color: '#8b5cf6', bg: 'bg-violet-500/15 text-violet-400' },
  technology: { label: 'Technology', color: '#3b82f6', bg: 'bg-blue-500/15 text-blue-400' },
  awareness: { label: 'Awareness', color: '#f97316', bg: 'bg-orange-500/15 text-orange-400' },
  guide: { label: 'Guide', color: '#06b6d4', bg: 'bg-cyan-500/15 text-cyan-400' },
};

const ALL_CATS = [{ slug: null, label: 'All' }, ...Object.entries(CAT_META).map(([slug, m]) => ({ slug, label: m.label }))];

function CategoryBadge({ category }) {
  const m = CAT_META[category];
  if (!m) return null;
  return <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${m.bg}`}>{m.label}</span>;
}

function PostCard({ post, onClick }) {
  const date = post.published_at ? new Date(post.published_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
  return (
    <article
      onClick={() => onClick(post.slug)}
      className="group cursor-pointer rounded-2xl bg-white/[0.03] border border-slate-800/40 hover:border-slate-700/60 transition-all duration-300 overflow-hidden"
      data-testid={`blog-card-${post.slug}`}
    >
      {post.featured_image_url && (
        <div className="h-44 overflow-hidden">
          <img src={post.featured_image_url} alt={post.title} loading="lazy"
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
        </div>
      )}
      <div className="p-5">
        <div className="flex items-center gap-2 mb-3">
          <CategoryBadge category={post.category} />
          <span className="text-[11px] text-slate-500">{date}</span>
        </div>
        <h2 className="text-base font-semibold text-white leading-snug mb-2 group-hover:text-violet-300 transition-colors line-clamp-2">
          {post.title}
        </h2>
        <p className="text-sm text-slate-400 leading-relaxed line-clamp-3 mb-3">{post.excerpt}</p>
        <div className="flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{post.read_time} min</span>
            <span className="flex items-center gap-1"><Eye className="w-3 h-3" />{post.views}</span>
          </div>
          <span className="text-violet-400 group-hover:translate-x-0.5 transition-transform">Read more</span>
        </div>
      </div>
    </article>
  );
}

export default function BlogListPage() {
  const navigate = useNavigate();
  const { category: urlCategory } = useParams();
  const [posts, setPosts] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeCat, setActiveCat] = useState(urlCategory || null);
  const [page, setPage] = useState(0);
  const LIMIT = 12;

  const loadPosts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: LIMIT, offset: page * LIMIT });
      if (activeCat) params.set('category', activeCat);
      const url = `https://nischint.care/api/blog?${params.toString()}`;
      const data = await cleanGet(url);
      setPosts(Array.isArray(data.posts) ? data.posts : []);
      setTotal(typeof data.total === 'number' ? data.total : 0);
    } catch (e) {
      console.error('Blog fetch error', e);
      setError(e.message || 'Failed to load articles');
      setPosts([]);
      setTotal(0);
    }
    setLoading(false);
  }, [activeCat, page]);

  useEffect(() => { loadPosts(); }, [loadPosts]);
  useEffect(() => { setActiveCat(urlCategory || null); setPage(0); }, [urlCategory]);

  const totalPages = Math.ceil(total / LIMIT);

  const pageTitle = activeCat
    ? `${CAT_META[activeCat]?.label || activeCat} Articles — NISCHINT Blog`
    : 'NISCHINT Blog — Safety Tips, Guides & Updates';

  // SEO meta via useEffect (Helmet crashes with dynamic titles in this codebase)
  useEffect(() => {
    document.title = pageTitle;
    const setMeta = (name, content) => {
      let el = document.querySelector(`meta[name="${name}"], meta[property="${name}"]`);
      if (!el) { el = document.createElement('meta'); el.setAttribute(name.startsWith('og:') ? 'property' : 'name', name); document.head.appendChild(el); }
      el.setAttribute('content', content);
    };
    setMeta('description', 'Expert safety guides, product updates, and awareness articles from NISCHINT — India\'s AI-powered family safety platform.');
    setMeta('og:title', pageTitle);
    setMeta('og:type', 'website');
    setMeta('og:url', `https://nischint.care/blog${activeCat ? `/category/${activeCat}` : ''}`);
    let canonical = document.querySelector('link[rel="canonical"]');
    if (!canonical) { canonical = document.createElement('link'); canonical.rel = 'canonical'; document.head.appendChild(canonical); }
    canonical.href = `https://nischint.care/blog${activeCat ? `/category/${activeCat}` : ''}`;
    return () => { document.title = 'NISCHINT'; };
  }, [pageTitle, activeCat]);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200" data-testid="blog-list-page">

      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2" data-testid="blog-nav-logo">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
              <Shield className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold tracking-tight">NISCHINT</span>
            <span className="text-xs text-slate-500 ml-1">/ Blog</span>
          </button>
          <button onClick={() => navigate('/')} className="text-xs text-slate-500 hover:text-white transition-colors" data-testid="blog-back-home">
            Back to Home
          </button>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-10">
        {/* Header */}
        <div className="mb-8">
          <nav className="flex items-center gap-1.5 text-xs text-slate-500 mb-4" data-testid="blog-breadcrumb">
            <button onClick={() => navigate('/')} className="hover:text-white transition-colors">Home</button>
            <ChevronRight className="w-3 h-3" />
            <button onClick={() => { setActiveCat(null); navigate('/blog'); }} className="hover:text-white transition-colors">Blog</button>
            {activeCat && (
              <>
                <ChevronRight className="w-3 h-3" />
                <span className="text-slate-300">{CAT_META[activeCat]?.label || activeCat}</span>
              </>
            )}
          </nav>
          <h1 className="text-3xl sm:text-4xl font-bold text-white mb-2">
            {activeCat ? CAT_META[activeCat]?.label : 'Blog'}
          </h1>
          <p className="text-base text-slate-400">Safety tips, product updates, and expert guides</p>
        </div>

        {/* Category Tabs */}
        <div className="flex gap-1.5 overflow-x-auto pb-1 mb-8 scrollbar-none" data-testid="blog-category-tabs">
          {ALL_CATS.map(c => (
            <button
              key={c.slug || 'all'}
              onClick={() => {
                setActiveCat(c.slug);
                setPage(0);
                if (c.slug) navigate(`/blog/category/${c.slug}`);
                else navigate('/blog');
              }}
              className={`px-4 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-colors ${
                activeCat === c.slug
                  ? 'bg-violet-500/15 text-violet-300 border border-violet-500/25'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.03]'
              }`}
              data-testid={`blog-cat-${c.slug || 'all'}`}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Grid */}
        {loading ? (
          <div className="flex items-center justify-center py-20" data-testid="blog-loading">
            <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
          </div>
        ) : error ? (
          <div className="text-center py-20" data-testid="blog-error">
            <Search className="w-10 h-10 text-red-700 mx-auto mb-4" />
            <p className="text-lg text-red-400 mb-1">Failed to load articles</p>
            <p className="text-sm text-slate-600 mb-4">{error}</p>
            <button onClick={loadPosts} className="px-4 py-2 rounded-lg text-xs font-medium bg-violet-500/20 text-violet-300 hover:bg-violet-500/30 transition-colors" data-testid="blog-retry-btn">
              Retry
            </button>
          </div>
        ) : posts.length === 0 ? (
          <div className="text-center py-20" data-testid="blog-empty">
            <Search className="w-10 h-10 text-slate-700 mx-auto mb-4" />
            <p className="text-lg text-slate-500 mb-1">No articles found</p>
            <p className="text-sm text-slate-600">
              {activeCat ? 'Try a different category.' : 'Blog posts coming soon!'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5" data-testid="blog-grid">
            {posts.map(p => <PostCard key={p.id} post={p} onClick={slug => navigate(`/blog/${slug}`)} />)}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-10" data-testid="blog-pagination">
            <button disabled={page === 0} onClick={() => setPage(p => p - 1)}
              className="px-4 py-2 rounded-lg text-xs font-medium bg-white/[0.04] text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              Previous
            </button>
            <span className="text-xs text-slate-500">
              Page {page + 1} of {totalPages}
            </span>
            <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}
              className="px-4 py-2 rounded-lg text-xs font-medium bg-white/[0.04] text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
