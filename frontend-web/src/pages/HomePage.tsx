import { ArrowRight, BookOpen, Brain, Eye, Feather, Palette, Sparkles, Users, Wand2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import './pages.css'

const features = [
  {
    icon: Wand2,
    title: 'AI 智能续写',
    description: '基于上下文自动续写情节，保持风格一致，让创作永不卡壳。',
  },
  {
    icon: Users,
    title: '角色引擎',
    description: '为每个角色赋予独特性格与背景，AI 确保角色行为始终合理。',
  },
  {
    icon: Brain,
    title: '世界观构建',
    description: '描述你的世界设定，AI 会在创作中自动维护时间线与逻辑一致性。',
  },
  {
    icon: Palette,
    title: '风格定制',
    description: '选择文学性、轻松、戏剧化等风格，AI 会匹配相应的文笔与节奏。',
  },
  {
    icon: BookOpen,
    title: '沉浸阅读',
    description: '专为长文本优化的阅读模式，护眼配色、可调字号，享受纸质书般的体验。',
  },
  {
    icon: Eye,
    title: '实时优化',
    description: '选中任意文本，AI 即刻提供润色、扩写、缩减等优化建议。',
  },
]

export function HomePage() {
  const navigate = useNavigate()

  return (
    <div className='home-page'>
      <section className='home-hero'>
        <div className='home-section__inner home-page__content'>
          <div className='hero-copy'>
            <div className='hero-copy__eyebrow'>
              <Sparkles size={14} />
              AI 驱动的创作体验
            </div>

            <h1 className='hero-title'>
              <span>用 AI 构建你的</span>
              <span className='hero-title__accent'>小说世界</span>
            </h1>

            <p>
              借助先进的 AI 技术，自动生成引人入胜的剧情、鲜活的角色和宏大的世界观。
              像聊天一样轻松创作，让灵感自由流淌。
            </p>

            <div className='hero-copy__actions'>
              <button type='button' className='primary-button hero-copy__button' onClick={() => navigate('/stories/new')}>
                <Feather size={18} />
                开始创作
                <ArrowRight size={16} />
              </button>
              <button type='button' className='secondary-button hero-copy__button' onClick={() => navigate('/stories')}>
                <BookOpen size={18} />
                浏览作品
              </button>
            </div>

            <div className='hero-copy__highlights'>
              <span>AI 实时生成</span>
              <span>多种题材风格</span>
              <span>沉浸式阅读</span>
            </div>
          </div>

          <div className='hero-visual'>
            <div className='hero-visual__glow' />
            <div className='hero-visual__board panel'>
              <div className='hero-visual__window'>
                <div className='dot dot--pink' />
                <div className='dot dot--yellow' />
                <div className='dot dot--green' />
              </div>
              <div className='hero-visual__bars'>
                <div />
                <div />
                <div />
                <div className='hero-visual__paper' />
              </div>
              <div className='hero-visual__quote'>
                “月光如水，洒落在古老的石板路上。少年抬头望向星空，心中涌起一股从未有过的力量...”
              </div>
              <div className='hero-visual__line hero-visual__line--long' />
              <div className='hero-visual__line hero-visual__line--mid' />
            </div>

            <div className='hero-visual__note panel'>
              <h4>
                <Sparkles size={14} />
                AI 建议
              </h4>
              <p>可以在这里加入一个神秘角色的出场，增加悬念...</p>
            </div>

            <div className='hero-visual__metric panel'>
              <span>今日创作</span>
              <strong>2,847</strong>
              <span>字</span>
            </div>
          </div>
        </div>
      </section>

      <section className='home-features'>
        <div className='home-section__inner'>
          <div className='home-section__heading'>
            <h2 className='home-section__title'>
              让 AI 成为你的<span className='hero-title__accent'>创作搭档</span>
            </h2>
            <p>从灵感闪现到完整作品，每一步都有 AI 智能辅助</p>
          </div>

          <div className='features-grid'>
            {features.map((feature) => {
              const Icon = feature.icon
              return (
                <article key={feature.title} className='feature-card panel'>
                  <div className='feature-card__icon'>
                    <Icon size={24} />
                  </div>
                  <h3>{feature.title}</h3>
                  <p>{feature.description}</p>
                </article>
              )
            })}
          </div>
        </div>
      </section>

      <section className='home-cta'>
        <div className='home-cta__inner'>
          <div className='home-cta__glow home-cta__glow--right' />
          <div className='home-cta__glow home-cta__glow--left' />
          <div className='home-cta__content'>
            <h2>准备好开启你的创作之旅了吗？</h2>
            <p>无需写作经验，AI 会引导你一步步构建属于自己的小说世界</p>
            <button type='button' className='home-cta__button' onClick={() => navigate('/stories/new')}>
              <Feather size={18} />
              立即开始创作
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </section>

      <footer className='home-footer'>
        <div className='home-footer__inner'>
          <div className='home-footer__brand'>
            墨韵<span className='hero-title__accent'>AI</span>
          </div>
          <p>© 2026 墨韵AI · 让每个人都能创作出色的小说</p>
        </div>
      </footer>
    </div>
  )
}
