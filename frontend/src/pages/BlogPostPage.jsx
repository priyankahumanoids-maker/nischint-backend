import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Shield, Clock, Eye, ChevronRight, Share2, ChevronDown, ChevronUp, ArrowRight, Loader2, MessageCircle, Linkedin, ExternalLink } from 'lucide-react';
import { cleanGet } from '../lib/cleanFetch';

const API = '';  // same-origin — no CORS, no stale baked-URL risk

const CAT_META = {
  women_safety: { label: 'Women Safety', bg: 'bg-pink-500/15 text-pink-400' },
  child_safety: { label: 'Child Safety', bg: 'bg-amber-500/15 text-amber-400' },
  family_safety: { label: 'Family Safety', bg: 'bg-emerald-500/15 text-emerald-400' },
  product: { label: 'Product', bg: 'bg-violet-500/15 text-violet-400' },
  technology: { label: 'Technology', bg: 'bg-blue-500/15 text-blue-400' },
  awareness: { label: 'Awareness', bg: 'bg-orange-500/15 text-orange-400' },
  guide: { label: 'Guide', bg: 'bg-cyan-500/15 text-cyan-400' },
};

function TableOfContents({ headings }) {
  if (!headings || headings.length === 0) return null;
  return (
    <nav className="p-4 rounded-xl bg-white/[0.03] border border-slate-800/40 mb-6" data-testid="blog-toc">
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Contents</h3>
      <ul className="space-y-1.5">
        {headings.map((h, i) => (
          <li key={i}>
            <a href={`#${h.id}`}
              className={`block text-sm hover:text-violet-300 transition-colors ${h.level === 3 ? 'pl-4 text-slate-500' : 'text-slate-400'}`}>
              {h.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function FAQSection({ faqs }) {
  const [openIdx, setOpenIdx] = useState(null);
  if (!faqs || faqs.length === 0) return null;
  return (
    <section className="mt-10" data-testid="blog-faq">
      <h2 className="text-xl font-bold text-white mb-5">Frequently Asked Questions</h2>
      <div className="space-y-2">
        {faqs.map((faq, i) => (
          <div key={i} className="rounded-xl border border-slate-800/40 overflow-hidden" data-testid={`faq-item-${i}`}>
            <button
              onClick={() => setOpenIdx(openIdx === i ? null : i)}
              className="w-full flex items-center justify-between p-4 text-left hover:bg-white/[0.02] transition-colors"
            >
              <span className="text-sm font-medium text-slate-200 pr-4">{faq.question}</span>
              {openIdx === i ? <ChevronUp className="w-4 h-4 text-slate-500 shrink-0" /> : <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />}
            </button>
            {openIdx === i && (
              <div className="px-4 pb-4 text-sm text-slate-400 leading-relaxed border-t border-slate-800/30 pt-3">
                {faq.answer}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function ShareButtons({ title, url }) {
  const encoded = encodeURIComponent(url);
  const encodedTitle = encodeURIComponent(title);
  const btns = [
    { label: 'WhatsApp', icon: MessageCircle, href: `https://wa.me/?text=${encodedTitle}%20${encoded}`, color: '#25D366' },
    { label: 'LinkedIn', icon: Linkedin, href: `https://www.linkedin.com/sharing/share-offsite/?url=${encoded}`, color: '#0077B5' },
    { label: 'Twitter', icon: ExternalLink, href: `https://twitter.com/intent/tweet?text=${encodedTitle}&url=${encoded}`, color: '#1DA1F2' },
  ];
  return (
    <div className="flex items-center gap-2" data-testid="blog-share">
      <Share2 className="w-3.5 h-3.5 text-slate-500" />
      {btns.map(b => (
        <a key={b.label} href={b.href} target="_blank" rel="noopener noreferrer"
          className="p-2 rounded-lg hover:bg-white/[0.06] transition-colors" title={`Share on ${b.label}`}
          data-testid={`share-${b.label.toLowerCase()}`}>
          <b.icon className="w-4 h-4" style={{ color: b.color }} />
        </a>
      ))}
    </div>
  );
}

function RelatedPosts({ posts, navigate }) {
  if (!posts || posts.length === 0) return null;
  return (
    <section className="mt-12" data-testid="blog-related">
      <h2 className="text-lg font-bold text-white mb-4">Related Articles</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {posts.map(p => (
          <article key={p.id} onClick={() => navigate(`/blog/${p.slug}`)}
            className="cursor-pointer p-4 rounded-xl bg-white/[0.03] border border-slate-800/40 hover:border-slate-700/60 transition-colors"
            data-testid={`related-${p.slug}`}>
            <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold mb-2 ${CAT_META[p.category]?.bg || 'bg-slate-800 text-slate-400'}`}>
              {CAT_META[p.category]?.label || p.category}
            </span>
            <h3 className="text-sm font-medium text-slate-200 line-clamp-2 mb-1">{p.title}</h3>
            <p className="text-xs text-slate-500">{p.read_time} min read</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export default function BlogPostPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [post, setPost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    cleanGet(`https://nischint.care/api/blog/${slug}`)
      .then(setPost)
      .catch(() => setError('Post not found'))
      .finally(() => setLoading(false));
  }, [slug]);

  // Extract headings from HTML for TOC
  const headings = useMemo(() => {
    if (!post?.content) return [];
    const re = /<(h[23])[^>]*>(.*?)<\/\1>/gi;
    const result = [];
    let match;
    while ((match = re.exec(post.content)) !== null) {
      const text = match[2].replace(/<[^>]+>/g, '');
      const id = text.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
      result.push({ level: parseInt(match[1][1]), text, id });
    }
    return result;
  }, [post?.content]);

  // Inject heading IDs and JSON-LD
  useEffect(() => {
    if (!post) return;
    // Add IDs to headings in rendered content
    const el = document.getElementById('blog-content');
    if (el) {
      el.querySelectorAll('h2, h3').forEach(heading => {
        const id = heading.textContent.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
        heading.id = id;
      });
    }
    // Inject JSON-LD
    const schemas = post.schema_json || [];
    const arr = Array.isArray(schemas) ? schemas : [schemas];
    const scripts = arr.map((s, i) => {
      const script = document.createElement('script');
      script.type = 'application/ld+json';
      script.id = `blog-schema-${i}`;
      script.textContent = JSON.stringify(s);
      document.head.appendChild(script);
      return script;
    });
    return () => scripts.forEach(s => s.remove());
  }, [post]);

  // SEO meta via useEffect (must be before early returns to satisfy Rules of Hooks)
  useEffect(() => {
    if (!post) return;
    const postUrl = `https://nischint.care/blog/${post.slug}`;
    document.title = post.meta_title || post.title;
    const setMeta = (attr, val, content) => {
      let el = document.querySelector(`meta[${attr}="${val}"]`);
      if (!el) { el = document.createElement('meta'); el.setAttribute(attr, val); document.head.appendChild(el); }
      el.setAttribute('content', content);
    };
    setMeta('name', 'description', post.meta_description || post.excerpt || '');
    setMeta('name', 'keywords', post.keywords || '');
    setMeta('property', 'og:title', post.meta_title || post.title);
    setMeta('property', 'og:description', post.meta_description || post.excerpt || '');
    setMeta('property', 'og:type', 'article');
    setMeta('property', 'og:url', postUrl);
    if (post.featured_image_url) setMeta('property', 'og:image', post.featured_image_url);
    setMeta('name', 'twitter:card', 'summary_large_image');
    setMeta('name', 'twitter:title', post.meta_title || post.title);
    setMeta('name', 'twitter:description', post.meta_description || post.excerpt || '');
    let canonical = document.querySelector('link[rel="canonical"]');
    if (!canonical) { canonical = document.createElement('link'); canonical.rel = 'canonical'; document.head.appendChild(canonical); }
    canonical.href = postUrl;
    return () => { document.title = 'NISCHINT'; };
  }, [post]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0e1a] flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    );
  }

  if (error || !post) {
    return (
      <div className="min-h-screen bg-[#0a0e1a] flex flex-col items-center justify-center text-center px-4">
        <h1 className="text-2xl font-bold text-white mb-2">Article Not Found</h1>
        <p className="text-slate-400 mb-6">The post you're looking for doesn't exist or has been removed.</p>
        <button onClick={() => navigate('/blog')} className="px-5 py-2.5 rounded-xl bg-violet-500/20 text-violet-300 text-sm font-medium hover:bg-violet-500/30 transition-colors">
          Back to Blog
        </button>
      </div>
    );
  }

  const date = post.published_at ? new Date(post.published_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' }) : '';
  const postUrl = `https://nischint.care/blog/${post.slug}`;
  const catMeta = CAT_META[post.category] || {};

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200" data-testid="blog-post-page">

      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2" data-testid="post-nav-logo">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
              <Shield className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold tracking-tight">NISCHINT</span>
          </button>
          <ShareButtons title={post.title} url={postUrl} />
        </div>
      </nav>

      <article className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1.5 text-xs text-slate-500 mb-6" data-testid="post-breadcrumb">
          <button onClick={() => navigate('/')} className="hover:text-white transition-colors">Home</button>
          <ChevronRight className="w-3 h-3" />
          <button onClick={() => navigate('/blog')} className="hover:text-white transition-colors">Blog</button>
          {post.category && (
            <>
              <ChevronRight className="w-3 h-3" />
              <button onClick={() => navigate(`/blog/category/${post.category}`)} className="hover:text-white transition-colors">
                {catMeta.label || post.category}
              </button>
            </>
          )}
          <ChevronRight className="w-3 h-3" />
          <span className="text-slate-400 truncate max-w-[200px]">{post.title}</span>
        </nav>

        {/* Header */}
        <header className="mb-8">
          {post.category && (
            <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold mb-4 ${catMeta.bg || 'bg-slate-800 text-slate-400'}`}>
              {catMeta.label || post.category}
            </span>
          )}
          <h1 className="text-3xl sm:text-4xl lg:text-[2.5rem] font-bold text-white leading-tight mb-4" data-testid="post-title">
            {post.title}
          </h1>
          <div className="flex flex-wrap items-center gap-4 text-sm text-slate-500">
            <span>{post.author}</span>
            <span>{date}</span>
            <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" />{post.read_time} min read</span>
            <span className="flex items-center gap-1"><Eye className="w-3.5 h-3.5" />{post.views} views</span>
          </div>
        </header>

        {/* Featured Image */}
        {post.featured_image_url && (
          <div className="rounded-2xl overflow-hidden mb-8 border border-slate-800/40">
            <img src={post.featured_image_url} alt={post.title} className="w-full h-auto object-cover" data-testid="post-hero-image" />
          </div>
        )}

        {/* Layout: Content + TOC */}
        <div className="flex gap-8">
          {/* Main content */}
          <div className="flex-1 min-w-0">
            <div
              id="blog-content"
              className="prose prose-invert prose-lg max-w-none
                prose-headings:text-white prose-headings:font-bold prose-headings:leading-tight
                prose-h2:text-2xl prose-h2:mt-10 prose-h2:mb-4
                prose-h3:text-xl prose-h3:mt-8 prose-h3:mb-3
                prose-p:text-slate-300 prose-p:leading-[1.75] prose-p:mb-5
                prose-a:text-violet-400 prose-a:no-underline hover:prose-a:underline
                prose-strong:text-white
                prose-ul:text-slate-300 prose-ol:text-slate-300
                prose-li:mb-1.5
                prose-blockquote:border-violet-500/40 prose-blockquote:text-slate-400
                prose-code:text-violet-300 prose-code:bg-violet-500/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded
                prose-img:rounded-xl prose-img:border prose-img:border-slate-800/40"
              data-testid="post-content"
              dangerouslySetInnerHTML={{ __html: post.content || '' }}
            />

            {/* FAQ */}
            <FAQSection faqs={post.faq_json} />

            {/* CTA Banner */}
            <div className="mt-12 p-6 sm:p-8 rounded-2xl bg-gradient-to-br from-violet-500/10 to-purple-500/10 border border-violet-500/20" data-testid="blog-cta">
              <h2 className="text-xl font-bold text-white mb-2">Keep your family safe with NISCHINT</h2>
              <p className="text-sm text-slate-400 mb-5">AI-powered live tracking, voice distress detection, and auto-escalation — real safety, not just a panic button.</p>
              <div className="flex flex-wrap gap-3">
                <a href="https://wa.me/919999999999?text=I%20want%20to%20setup%20Nischint%20safety"
                  target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#25D366] text-white text-sm font-semibold hover:brightness-110 transition-all"
                  data-testid="cta-whatsapp">
                  <MessageCircle className="w-4 h-4" /> Get Started on WhatsApp
                </a>
                <button onClick={() => navigate('/pilot')}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/[0.06] text-slate-300 text-sm font-medium hover:bg-white/[0.1] border border-slate-700/50 transition-colors"
                  data-testid="cta-demo">
                  Book a Demo <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Related */}
            <RelatedPosts posts={post.related_posts} navigate={navigate} />
          </div>

          {/* Sidebar TOC (desktop only) */}
          {headings.length > 0 && (
            <aside className="hidden lg:block w-56 shrink-0">
              <div className="sticky top-20">
                <TableOfContents headings={headings} />
              </div>
            </aside>
          )}
        </div>
      </article>
    </div>
  );
}
