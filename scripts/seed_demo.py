"""生成 3 篇符合完整 Schema 的高质量示例外刊精读 JSON。

用途：在受限网络环境下，让前台所有精读交互（生词浮窗、双语、长难句、词表联动、
搜索、Anki 导出）可以直接演示验收。运行：

    python -m scripts.seed_demo

产物：
    data/parsed/<id>.json   × 3
    data/index.json         （由 Storage 统一维护）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.console import ensure_utf8_console  # noqa: E402

ensure_utf8_console()

from src.models import (  # noqa: E402
    ArticleOverview,
    Difficulty,
    ParagraphPair,
    ParsedArticle,
    SentenceAnalysis,
    VocabItem,
)
from src.storage import Storage  # noqa: E402
from src.utils import iso_now, read_time_minutes, url_hash  # noqa: E402


# ---------------------------------------------------------------------------
# 示例 1：Aeon —— 注意力建筑学（心理学 / 文化）
# ---------------------------------------------------------------------------

AEON_PARAGRAPHS: list[tuple[str, str]] = [
    (
        "For most of human history, attention was not something a person owned outright. It was "
        "borrowed from the room: from the fire that had to be watched, the child who had to be "
        "minded, the horizon that had to be scanned for weather or riders. To be attentive was to "
        "be answerable to something outside yourself, and the quality of a life could be read in "
        "how faithfully that answer was given.",
        "在人类历史的大部分时间里，注意力并不是一个人可以完全拥有的东西。它更像是从所处的空间里借来的："
        "火堆需要看守，孩子需要照看，地平线需要不时张望，以便发现天气变化或骑马而来的访客。"
        "专注意味着对自身之外的某样东西负责，而一个人生活的质地，也可以从他对这份责任履行的忠实程度中看出来。",
    ),
    (
        "The modern word carries a different weight. We speak of paying attention, as though it were "
        "currency, and of spending it wisely, as though a day had a fixed exchange rate. This "
        "metaphor is not innocent. Once attention is conceived as a scarce resource that individuals "
        "possess, it becomes natural to ask who is entitled to extract it, and at what price — and "
        "equally natural for entire industries to organise themselves around the answer.",
        "现代语境里的这个词带着另一重分量。我们说“付出”注意力，仿佛它是一种货币；又说要“明智地花掉”它，"
        "仿佛一天有一个固定的汇率。这个比喻并不无辜。一旦注意力被设想为个体所拥有的稀缺资源，"
        "追问谁有权开采它、以什么价格开采，就变得顺理成章；整个行业围绕这个答案组织自身，也同样顺理成章。",
    ),
    (
        "What the metaphor obscures is the extent to which attention is built rather than held. "
        "A room can be arranged so that conversation is easy and interruption is difficult, or the "
        "reverse. A street can be designed to reward lingering or to hurry people along. These are "
        "not decorative choices. They are the architecture of an attentional commons, and like any "
        "commons, it can be enclosed, depleted, or deliberately restored.",
        "这个比喻所遮蔽的，是注意力在多大程度上是被建造出来的，而非被持有的。"
        "一间屋子可以被安排得让交谈轻松、打扰困难，也可以反过来。一条街道可以被设计成鼓励人逗留，"
        "或催促人快走。这些都不是装饰性的选择，而是一片注意力公地的建筑学；而和任何公地一样，"
        "它可以被圈占、被耗尽，也可以被有意修复。",
    ),
    (
        "Consider the reading room. For a century and a half it was among the most carefully "
        "engineered spaces in civic life: long tables aligned to a single source of daylight, "
        "catalogues placed at the threshold so that the walk to a shelf was itself a transition, "
        "and a rule of silence that was less about noise than about the visible consent of everyone "
        "present. The silence did not merely permit concentration; it produced it, by making "
        "distraction socially expensive.",
        "不妨想想阅览室。在一个半世纪里，它一直是公共生活中设计得最用心的空间之一："
        "长桌朝向唯一的自然光源排列，目录柜放在入口处，让走向书架的那段路本身成为一种过渡，"
        "而那条静默的规矩与其说关乎噪音，不如说关乎在场每个人可见的同意。"
        "这份静默不只是允许专注，它生产专注——因为它让分心在社会层面变得代价高昂。",
    ),
    (
        "Digital environments invert that logic with impressive efficiency. They make distraction "
        "cheap and concentration faintly embarrassing, as though stillness were a failure to "
        "participate. The result is not that people have become weaker willed, but that the "
        "materials around them have been re-engineered to reward a different behaviour. Blaming "
        "individuals for this is like blaming a pedestrian for the absence of pavements.",
        "数字环境以惊人的效率把这一逻辑颠倒过来。它们让分心变得廉价，让专注反而略显尴尬，"
        "仿佛静止不动是一种不参与。结果并不是人们变得更意志薄弱，而是周遭的材料被重新设计，"
        "以奖励另一种行为。为此责备个人，就像因为没有人行道而责备行人。",
    ),
    (
        "There is a practical corollary. If attention is architectural, then it can be rebuilt "
        "deliberately — not through resolutions, which are fragile, but through rooms, schedules "
        "and defaults, which are not. The most reliable interventions are the least heroic: a door "
        "that closes, a device that lives in another room, an hour in which nobody expects a reply. "
        "We tend to underestimate these because they are unglamorous, and to overestimate willpower "
        "because it feels like character.",
        "这里有一个实际的推论。如果注意力是建筑性的，那它就可以被有意重建——不是靠决心，"
        "因为决心脆弱；而是靠房间、日程与默认设置，因为它们并不脆弱。最可靠的干预往往最不英勇："
        "一扇关上的门，一台放在另一个房间的设备，一段没有人期待回复的时间。"
        "我们倾向于低估这些，因为它们不够光鲜；又倾向于高估意志力，因为它感觉像品格。",
    ),
    (
        "The deeper question is what kind of attention a society wishes to make easy. Every "
        "arrangement answers it, whether or not anyone states the answer aloud. A culture that "
        "furnishes its public spaces for lingering has decided something about the worth of "
        "unhurried thought; one that furnishes them for throughput has decided something else. "
        "The choice is rarely presented as a choice, which is precisely why it deserves to be named.",
        "更深一层的问题是：一个社会希望让哪一种注意力变得容易？每一种安排都在回答这个问题，"
        "无论有没有人把答案说出口。一个把公共空间布置成供人逗留的文化，已经就从容思考的价值做出了决断；"
        "一个把它们布置成追求吞吐量的文化，则做出了另一种决断。这个选择很少被摆到台面上作为选择，"
        "而这恰恰是它值得被点名的原因。",
    ),
]

AEON_VOCAB = [
    VocabItem(id="v1", term="answerable", phonetic="/ˈɑːn.sər.ə.bəl/", pos="adj.",
              meaning_zh="对……负责的；须作出交代的",
              note="常与 to 连用：be answerable to someone for something", para_index=0),
    VocabItem(id="v2", term="not innocent", phonetic="/nɒt ˈɪn.ə.sənt/", pos="phrase",
              meaning_zh="并非无邪／中性的（暗含价值预设）", note="学术写作中常用来指出某个隐喻本身携带立场", para_index=1),
    VocabItem(id="v3", term="entitled", phonetic="/ɪnˈtaɪ.təld/", pos="adj.",
              meaning_zh="有资格（享有）的；被赋予权利的",
              note="be entitled to do something：有权做某事", para_index=1),
    VocabItem(id="v4", term="obscures", phonetic="/əbˈskjʊəz/", pos="v.",
              meaning_zh="遮蔽；使模糊不清", note="obscure 作动词时常用于“使某事实不易被看见”", para_index=2),
    VocabItem(id="v5", term="attentional commons", phonetic="/əˈten.ʃən.əl ˈkɒm.ənz/", pos="phrase",
              meaning_zh="注意力公地（共享且易被耗竭的集体资源）", note="由 commons（公地）这一政治经济学概念延伸而来", para_index=2),
    VocabItem(id="v6", term="enclosed", phonetic="/ɪnˈkləʊzd/", pos="adj.",
              meaning_zh="被圈占的；被围起来的", note="enclosure 指历史上对公共土地的圈占，此处为隐喻", para_index=2),
    VocabItem(id="v7", term="depleted", phonetic="/dɪˈpliː.tɪd/", pos="adj.",
              meaning_zh="被耗尽的；枯竭的", note="常与 resources / soil / energy 搭配", para_index=2),
    VocabItem(id="v8", term="engineered", phonetic="/ˌen.dʒɪˈnɪəd/", pos="adj.",
              meaning_zh="被精心设计（工程化）的", note="比 designed 更强调系统性、有意识的技术安排", para_index=3),
    VocabItem(id="v9", term="threshold", phonetic="/ˈθreʃ.həʊld/", pos="n.",
              meaning_zh="门槛；入口处", note="此处取字面义，与抽象的“阈限”义并存", para_index=3),
    VocabItem(id="v10", term="consent", phonetic="/kənˈsent/", pos="n.",
              meaning_zh="同意；默许", note="visible consent：可见的、彼此默认的同意", para_index=3),
    VocabItem(id="v11", term="invert", phonetic="/ɪnˈvɜːt/", pos="v.",
              meaning_zh="颠倒；使反向", note="invert the logic：把逻辑倒转过来", para_index=4),
    VocabItem(id="v12", term="faintly", phonetic="/ˈfeɪnt.li/", pos="adv.",
              meaning_zh="隐约地；略微地", note="faintly embarrassing：略微尴尬，程度副词弱化语气", para_index=4),
    VocabItem(id="v13", term="corollary", phonetic="/kəˈrɒl.ər.i/", pos="n.",
              meaning_zh="推论；必然的结果", note="formal，常见于论证型文章", para_index=5),
    VocabItem(id="v14", term="unglamorous", phonetic="/ʌnˈɡlæm.ər.əs/", pos="adj.",
              meaning_zh="不光鲜的；不起眼的", note="由 glamour 加否定前缀构成", para_index=5),
    VocabItem(id="v15", term="throughput", phonetic="/ˈθruː.pʊt/", pos="n.",
              meaning_zh="吞吐量；处理量", note="工程与运营术语，此处指单位时间内通过的人流", para_index=6),
]

AEON_SENTENCES = [
    SentenceAnalysis(
        en="Once attention is conceived as a scarce resource that individuals possess, it becomes "
           "natural to ask who is entitled to extract it, and at what price — and equally natural "
           "for entire industries to organise themselves around the answer.",
        structure="主干：it becomes natural to ask… and [it becomes] equally natural for industries to organise… ｜ "
                  "状语从句：Once attention is conceived as…（被动） ｜ 定语从句：that individuals possess 修饰 resource ｜ "
                  "宾语从句：who is entitled to extract it, and at what price",
        zh="一旦注意力被设想为个体所拥有的稀缺资源，追问谁有权开采它、以什么价格开采就变得顺理成章；"
           "而整个行业围绕这个答案组织自身，也同样顺理成章。",
    ),
    SentenceAnalysis(
        en="What the metaphor obscures is the extent to which attention is built rather than held.",
        structure="主语从句：What the metaphor obscures ｜ 系动词 is ｜ 表语：the extent ｜ 定语从句：to which attention is built rather than held"
                  "（介词前置 + 并列被动结构）",
        zh="这个比喻所遮蔽的，是注意力在多大程度上是被建造出来的，而非被持有的。",
    ),
    SentenceAnalysis(
        en="The silence did not merely permit concentration; it produced it, by making distraction "
           "socially expensive.",
        structure="并列句：did not merely permit… ; it produced it ｜ 方式状语：by making distraction socially expensive"
                  "（make + 宾语 + 形容词补足语）",
        zh="这份静默不只是允许专注，它生产专注——因为它让分心在社会层面变得代价高昂。",
    ),
    SentenceAnalysis(
        en="Blaming individuals for this is like blaming a pedestrian for the absence of pavements.",
        structure="动名词短语作主语：Blaming individuals for this ｜ 表语：like blaming a pedestrian for…（类比结构，"
                  "用具体失当的归责反衬结构性原因）",
        zh="为此责备个人，就像因为没有人行道而责备行人。",
    ),
    SentenceAnalysis(
        en="We tend to underestimate these because they are unglamorous, and to overestimate "
           "willpower because it feels like character.",
        structure="主干：We tend to underestimate these … and [tend] to overestimate willpower ｜ "
                  "两个并列原因状语从句：because they are unglamorous / because it feels like character",
        zh="我们倾向于低估这些，因为它们不够光鲜；又倾向于高估意志力，因为它感觉像品格。",
    ),
]


# ---------------------------------------------------------------------------
# 示例 2：Quanta Magazine —— 数学／物理（C2）
# ---------------------------------------------------------------------------

QUANTA_PARAGRAPHS: list[tuple[str, str]] = [
    (
        "In 1964, a young physicist named John Bell published a short paper that asked a question "
        "no one had quite known how to pose. If quantum mechanics were true, he wondered, could the "
        "world still be made of things that had definite properties before anyone measured them? "
        "The answer, expressed as an inequality, was a precise no.",
        "1964 年，一位名叫约翰·贝尔的年轻物理学家发表了一篇短文，提出了一个此前没有人真正知道该如何表述的问题。"
        "他想：如果量子力学是真的，这个世界是否仍然由那些在被测量之前就拥有确定属性的东西构成？"
        "答案以一个不等式呈现，是一个精确的“否”。",
    ),
    (
        "The inequality was remarkable not for its mathematics, which was elementary, but for its "
        "ambition. It translated a dispute that had smouldered for decades — between those who "
        "believed quantum theory was a complete description of reality and those who suspected it "
        "was merely a convenient approximation — into something that an experiment could settle. "
        "Philosophy became protocol.",
        "这个不等式之所以引人注目，不在于它的数学——那是初等的——而在于它的雄心。"
        "它把一场闷烧了数十年的争论——相信量子理论是对现实的完整描述的人，与怀疑它只是权宜近似的人之间的争论——"
        "转化为某种实验可以裁定的事情。哲学变成了实验方案。",
    ),
    (
        "Half a century later, the experiments were done, and Bell was vindicated. Entangled "
        "particles, measured far apart, produced correlations that no account of locally "
        "pre-existing properties could reproduce. The loopholes closed one by one: detection "
        "efficiency, communication, freedom of choice. What remained was not a paradox but a "
        "constraint — a hard limit on what kind of world we are allowed to describe.",
        "半个世纪后，实验完成了，贝尔得到了证实。彼此相距遥远却纠缠的粒子，在被测量时产生了任何关于局部预先存在属性的解释都无法重现的关联性。"
        "各种漏洞逐一被封闭：探测效率、通信、选择自由。留下来的不是一个悖论，而是一种约束——"
        "一道关于我们被允许描述何种世界的硬性界限。",
    ),
    (
        "What the constraint forbids is precise but easy to overstate. It does not forbid realism, "
        "the view that there is a world independent of our observations. Nor does it forbid "
        "determinism, the view that everything follows from prior conditions. It forbids the "
        "conjunction of the two with locality — the assumption that influences travel no faster "
        "than light and that distant events cannot depend on the settings of a nearby dial.",
        "这道约束所禁止的东西是精确的，却很容易被夸大。它并不禁止实在论——即存在一个独立于我们观察的世界；"
        "也不禁止决定论——即一切皆由先前条件决定。它禁止的是这两者与定域性的结合——"
        "那个假设：影响传播不快于光速，且遥远事件不可能依赖于近处某个旋钮的设置。",
    ),
    (
        "Physicists have learned to live with this in the way that working scientists usually "
        "learn to live with deep constraints: by not asking too often. Quantum theory predicts "
        "with extraordinary precision, and the predictions are what matter for most purposes. But "
        "the interpretation question has not gone away, and it resurfaces each time a new "
        "technology makes entanglement an engineering material rather than a curiosity.",
        "物理学家已经学会了与这一点共处，用的是在职科学家通常学会与深层约束共处的方式：不把这个问题问得太频繁。"
        "量子理论的预测精确得非同寻常，而对多数用途来说，重要的正是那些预测。"
        "但诠释问题并没有消失；每当一项新技术把纠缠从奇趣变成工程材料，它就会重新浮现。",
    ),
    (
        "This is where the argument becomes interesting again. A constraint that once seemed to be "
        "about metaphysics now bears directly on cryptography, computing and metrology. Devices "
        "that exploit entanglement are, in effect, machines built from a philosophical result. The "
        "engineers who build them rarely describe their work that way, and they do not need to. "
        "But the result is doing the work all the same.",
        "这正是争论重新变得有趣的地方。一道曾看似关乎形而上学的约束，如今直接作用于密码学、计算与计量学。"
        "利用纠缠的装置，实际上是建立在一条哲学结论之上的机器。制造它们的工程师很少这样描述自己的工作，"
        "也无需如此。但那条结论始终在起作用。",
    ),
]

QUANTA_VOCAB = [
    VocabItem(id="v1", term="definite", phonetic="/ˈdef.ɪ.nət/", pos="adj.",
              meaning_zh="确定的；明确的", note="definite properties：确定属性，与 indefinite 相对", para_index=0),
    VocabItem(id="v2", term="inequality", phonetic="/ˌɪn.ɪˈkwɒl.ə.ti/", pos="n.",
              meaning_zh="不等式；不平等", note="数学语境里指 Bell inequality 这类不等式关系", para_index=0),
    VocabItem(id="v3", term="elementary", phonetic="/ˌel.ɪˈmen.tər.i/", pos="adj.",
              meaning_zh="初等的；基本的", note="elementary mathematics：初等数学（并非“小学的”）", para_index=1),
    VocabItem(id="v4", term="smouldered", phonetic="/ˈsməʊl.dəd/", pos="v.",
              meaning_zh="（争论、情绪）郁积；闷烧", note="英式拼写；美式为 smoldered，常作隐喻", para_index=1),
    VocabItem(id="v5", term="approximation", phonetic="/əˌprɒk.sɪˈmeɪ.ʃən/", pos="n.",
              meaning_zh="近似；近似值", note="a convenient approximation：权宜的近似", para_index=1),
    VocabItem(id="v6", term="protocol", phonetic="/ˈprəʊ.tə.kɒl/", pos="n.",
              meaning_zh="规程；实验方案", note="此处双关：既指实验流程，也暗指哲学被“程序化”", para_index=1),
    VocabItem(id="v7", term="vindicated", phonetic="/ˈvɪn.dɪ.keɪ.tɪd/", pos="adj.",
              meaning_zh="被证明正确的；得到辩白的", note="vindicate someone's view：证明某人的看法成立", para_index=2),
    VocabItem(id="v8", term="entangled", phonetic="/ɪnˈtæŋ.ɡəld/", pos="adj.",
              meaning_zh="（量子）纠缠的；缠绕的", note="quantum entanglement：量子纠缠", para_index=2),
    VocabItem(id="v9", term="correlations", phonetic="/ˌkɒr.əˈleɪ.ʃənz/", pos="n.",
              meaning_zh="相关性；（统计）关联", note="实验中指测量结果之间的统计相关", para_index=2),
    VocabItem(id="v10", term="loopholes", phonetic="/ˈluːp.həʊlz/", pos="n.",
              meaning_zh="（规则中的）漏洞；可乘之隙", note="close the loopholes：封堵漏洞", para_index=2),
    VocabItem(id="v11", term="paradox", phonetic="/ˈpær.ə.dɒks/", pos="n.",
              meaning_zh="悖论；看似矛盾之说", note="与 constraint（约束）形成对照论证", para_index=2),
    VocabItem(id="v12", term="overstate", phonetic="/ˌəʊ.vəˈsteɪt/", pos="v.",
              meaning_zh="夸大；言过其实", note="easy to overstate：很容易被夸大", para_index=3),
    VocabItem(id="v13", term="determinism", phonetic="/dɪˈtɜː.mɪ.nɪ.zəm/", pos="n.",
              meaning_zh="决定论", note="哲学概念：一切由先前条件决定", para_index=3),
    VocabItem(id="v14", term="conjunction", phonetic="/kənˈdʒʌŋk.ʃən/", pos="n.",
              meaning_zh="结合；同时成立", note="the conjunction of A with B：A 与 B 的合取", para_index=3),
    VocabItem(id="v15", term="metrology", phonetic="/mɪˈtrɒl.ə.dʒi/", pos="n.",
              meaning_zh="计量学；测量科学", note="精密测量领域，与 quantum sensing 密切相关", para_index=5),
]

QUANTA_SENTENCES = [
    SentenceAnalysis(
        en="If quantum mechanics were true, he wondered, could the world still be made of things "
           "that had definite properties before anyone measured them?",
        structure="间接疑问句：he wondered + whether/if 从句（此处为疑问语序嵌套） ｜ "
                  "条件状语从句：If quantum mechanics were true（虚拟语气 were） ｜ 定语从句：that had definite properties…",
        zh="他想：如果量子力学是真的，这个世界是否仍然由那些在被测量之前就拥有确定属性的东西构成？",
    ),
    SentenceAnalysis(
        en="It translated a dispute that had smouldered for decades — between those who believed "
           "quantum theory was a complete description of reality and those who suspected it was "
           "merely a convenient approximation — into something that an experiment could settle.",
        structure="主干：It translated a dispute … into something ｜ 定语从句：that had smouldered for decades ｜ "
                  "同位插入语：between those who… and those who…（两个 who 定语从句） ｜ 定语从句：that an experiment could settle",
        zh="它把一场闷烧了数十年的争论——相信量子理论是对现实的完整描述的人，与怀疑它只是权宜近似的人之间的争论——"
           "转化为某种实验可以裁定的事情。",
    ),
    SentenceAnalysis(
        en="What remained was not a paradox but a constraint — a hard limit on what kind of world we "
           "are allowed to describe.",
        structure="主语从句：What remained ｜ 表语：not a paradox but a constraint（not…but… 并列） ｜ "
                  "同位语破折号补充：a hard limit ｜ 介词宾语从句：on what kind of world we are allowed to describe",
        zh="留下来的不是一个悖论，而是一种约束——一道关于我们被允许描述何种世界的硬性界限。",
    ),
    SentenceAnalysis(
        en="It forbids the conjunction of the two with locality — the assumption that influences "
           "travel no faster than light and that distant events cannot depend on the settings of a "
           "nearby dial.",
        structure="主干：It forbids the conjunction of A with B ｜ 同位语：the assumption ｜ "
                  "两个并列 that 同位语从句：that influences travel… / that distant events cannot depend on…",
        zh="它禁止的是这两者与定域性的结合——那个假设：影响传播不快于光速，且遥远事件不可能依赖于近处某个旋钮的设置。",
    ),
    SentenceAnalysis(
        en="Devices that exploit entanglement are, in effect, machines built from a philosophical "
           "result.",
        structure="主干：Devices are machines ｜ 定语从句：that exploit entanglement ｜ 插入语：in effect ｜ "
                  "过去分词短语作后置定语：built from a philosophical result",
        zh="利用纠缠的装置，实际上是建立在一条哲学结论之上的机器。",
    ),
]


# ---------------------------------------------------------------------------
# 示例 3：MIT Technology Review —— 科技／商业（C1）
# ---------------------------------------------------------------------------

MIT_PARAGRAPHS: list[tuple[str, str]] = [
    (
        "The data centre industry has a number that it prefers not to say out loud. It is not the "
        "capital cost of a new campus, nor the water consumed by cooling towers, though both are "
        "substantial. It is the fraction of a facility's electricity that actually reaches a "
        "processor. In well-run modern sites, that figure is around 90%; in the older stock still "
        "carrying much of the world's workload, it is considerably worse.",
        "数据中心行业有一个它不太愿意公开说出的数字。它不是新建园区的资本开支，也不是冷却塔消耗的水——虽然这两者都相当可观。"
        "它是设施用电中真正抵达处理器的比例。在运营良好的现代机房，这个数字约为 90%；"
        "而在仍承载着全球大量工作负载的旧设施里，它要差得多。",
    ),
    (
        "This is not a story about engineering incompetence. The inefficiency is largely a "
        "consequence of how capacity was bought: in increments, under pressure, with an eye on "
        "time-to-service rather than on lifetime thermodynamics. A facility designed around the "
        "assumption that compute would remain expensive will distribute power differently from one "
        "designed around the assumption that it would become cheap and plentiful.",
        "这并不是一个关于工程无能的故事。这种低效率在很大程度上是容量采购方式的后果："
        "分批次、在压力之下、着眼于上线时间而非全生命周期的热力学。"
        "一个按“算力将持续昂贵”这一假设设计的数据中心，其配电方式会不同于按“算力将变得廉价而充裕”设计的机房。",
    ),
    (
        "The consequence is that the cost of computation is increasingly a power problem rather "
        "than a silicon problem. Chip designers can now pack more arithmetic into less space than "
        "the surrounding infrastructure can usefully feed. The bottleneck has migrated outward — "
        "from the transistor to the transformer, from the processor to the substation, from the "
        "server to the queue for a grid connection that may take years to clear.",
        "其后果是，计算成本越来越是一个电力问题，而不是一个硅的问题。芯片设计师如今能在更小的空间里塞进更多算力，"
        "多到周边基础设施无法有效供给。瓶颈向外迁移了——从晶体管到变压器，从处理器到变电站，"
        "从服务器到并网排队，而这条队伍可能要等上数年。",
    ),
    (
        "Grid interconnection queues have become the industry's least glamorous constraint and its "
        "most decisive one. In several markets the wait for a new high-voltage connection is "
        "measured in years, and the queue is not first-come-first-served in any simple sense: it "
        "is shaped by studies, deposits, and the willingness of a developer to accept curtailment. "
        "A project can be technically ready and commercially stalled at the same time.",
        "并网排队已成为这个行业最不光鲜、也最具决定性的约束。在若干市场，等待一条新的高压接入要按年计算，"
        "而这支队伍也并非简单意义上的先到先得：它由研究评估、押金，以及开发商是否愿意接受限电共同塑造。"
        "一个项目完全可能技术上已就绪，商业上却停滞不前。",
    ),
    (
        "Against this backdrop, the enthusiasm for on-site generation becomes legible. Gas turbines "
        "can be permitted and built faster than transmission lines; small modular reactors promise "
        "a slower but steadier answer; solar-plus-storage is cheap where land is. None of these is "
        "a universal solution, and each shifts the problem rather than dissolving it. But they "
        "shorten the distance between a decision and a watt.",
        "在这一背景下，对就地发电的热情就变得可以理解了。燃气轮机比输电线路更容易获得许可、建设更快；"
        "小型模块化反应堆承诺一个更慢但更稳的答案；在土地便宜的地方，光伏加储能成本很低。"
        "这些都不是普适解法，每一种都只是转移问题而非消解问题。但它们缩短了从决策到一度电之间的距离。",
    ),
    (
        "The strategic implication is uncomfortable for an industry that has spent two decades "
        "optimising inside the fence line. The decisive variables now sit outside it: the pace of "
        "grid reform, the politics of siting, the availability of skilled electrical labour. Firms "
        "that treat these as externalities will find their capital plans repeatedly surprised by "
        "them. Firms that treat them as core engineering will not.",
        "对于一个用二十年时间在围墙之内做优化的行业来说，这一战略含义令人不适。决定性的变量如今位于围墙之外："
        "电网改革的速度、选址的政治、熟练电气劳动力的可得性。把这些当作外部性的公司，会发现自己的资本计划一再被它们打乱；"
        "把它们当作核心工程的公司则不会。",
    ),
]

MIT_VOCAB = [
    VocabItem(id="v1", term="substantial", phonetic="/səbˈstæn.ʃəl/", pos="adj.",
              meaning_zh="可观的；相当大的", note="比 large 更正式，常用于数量与影响", para_index=0),
    VocabItem(id="v2", term="fraction", phonetic="/ˈfræk.ʃən/", pos="n.",
              meaning_zh="份额；一小部分", note="a fraction of：……的一部分（可大可小，视语境）", para_index=0),
    VocabItem(id="v3", term="increments", phonetic="/ˈɪŋ.krɪ.mənts/", pos="n.",
              meaning_zh="增量；分批的份额", note="in increments：分批次地", para_index=1),
    VocabItem(id="v4", term="thermodynamics", phonetic="/ˌθɜː.məʊ.daɪˈnæm.ɪks/", pos="n.",
              meaning_zh="热力学", note="此处指机房长期的热与能效表现", para_index=1),
    VocabItem(id="v5", term="bottleneck", phonetic="/ˈbɒt.əl.nek/", pos="n.",
              meaning_zh="瓶颈；制约环节", note="the bottleneck has migrated：瓶颈已转移", para_index=2),
    VocabItem(id="v6", term="migrated", phonetic="/maɪˈɡreɪ.tɪd/", pos="v.",
              meaning_zh="迁移；转移", note="此处为隐喻用法，非人口迁徙", para_index=2),
    VocabItem(id="v7", term="substation", phonetic="/ˈsʌbˌsteɪ.ʃən/", pos="n.",
              meaning_zh="变电站", note="电网术语，与 transformer 常并列出现", para_index=2),
    VocabItem(id="v8", term="interconnection", phonetic="/ˌɪn.tə.kəˈnek.ʃən/", pos="n.",
              meaning_zh="互联；并网接入", note="grid interconnection queue：并网排队", para_index=3),
    VocabItem(id="v9", term="curtailment", phonetic="/kɜːˈteɪl.mənt/", pos="n.",
              meaning_zh="限电；削减出力", note="accept curtailment：接受被限电的风险", para_index=3),
    VocabItem(id="v10", term="stalled", phonetic="/stɔːld/", pos="adj.",
              meaning_zh="停滞的；卡住的", note="commercially stalled：商业上停滞", para_index=3),
    VocabItem(id="v11", term="legible", phonetic="/ˈledʒ.ə.bəl/", pos="adj.",
              meaning_zh="可读的；（此处）变得可理解的", note="本义“字迹清晰”，此处引申为“说得通”", para_index=4),
    VocabItem(id="v12", term="modular", phonetic="/ˈmɒd.jə.lər/", pos="adj.",
              meaning_zh="模块化的", note="small modular reactor（SMR）：小型模块化反应堆", para_index=4),
    VocabItem(id="v13", term="dissolving", phonetic="/dɪˈzɒl.vɪŋ/", pos="v.",
              meaning_zh="消解；使消失", note="shifts the problem rather than dissolving it：转移而非消解", para_index=4),
    VocabItem(id="v14", term="externalities", phonetic="/ˌek.stɜːˈnæl.ə.tiz/", pos="n.",
              meaning_zh="外部性（未计入决策的成本或收益）", note="经济学核心概念，此处指被企业忽略的外部约束", para_index=5),
    VocabItem(id="v15", term="decisive", phonetic="/dɪˈsaɪ.sɪv/", pos="adj.",
              meaning_zh="决定性的；关键的", note="decisive variables：决定性变量", para_index=5),
]

MIT_SENTENCES = [
    SentenceAnalysis(
        en="It is not the capital cost of a new campus, nor the water consumed by cooling towers, "
           "though both are substantial.",
        structure="主干：It is not A, nor B（并列否定） ｜ 过去分词短语作定语：consumed by cooling towers ｜ "
                  "让步状语从句：though both are substantial",
        zh="它不是新建园区的资本开支，也不是冷却塔消耗的水——虽然这两者都相当可观。",
    ),
    SentenceAnalysis(
        en="A facility designed around the assumption that compute would remain expensive will "
           "distribute power differently from one designed around the assumption that it would "
           "become cheap and plentiful.",
        structure="主干：A facility … will distribute power differently from one ｜ 过去分词短语作定语：designed around the assumption ｜ "
                  "两个同位语从句：that compute would remain expensive / that it would become cheap and plentiful",
        zh="一个按“算力将持续昂贵”这一假设设计的数据中心，其配电方式会不同于按“算力将变得廉价而充裕”设计的机房。",
    ),
    SentenceAnalysis(
        en="Chip designers can now pack more arithmetic into less space than the surrounding "
           "infrastructure can usefully feed.",
        structure="主干：Chip designers can pack more arithmetic into less space ｜ 比较结构：more … than the surrounding "
                  "infrastructure can usefully feed（比较对象为“可供给的量”）",
        zh="芯片设计师如今能在更小的空间里塞进更多算力，多到周边基础设施无法有效供给。",
    ),
    SentenceAnalysis(
        en="The queue is not first-come-first-served in any simple sense: it is shaped by studies, "
           "deposits, and the willingness of a developer to accept curtailment.",
        structure="主干：The queue is not first-come-first-served ｜ 冒号后为解释性并列句 ｜ 被动结构：is shaped by A, B, and C",
        zh="这支队伍也并非简单意义上的先到先得：它由研究评估、押金，以及开发商是否愿意接受限电共同塑造。",
    ),
    SentenceAnalysis(
        en="Firms that treat these as externalities will find their capital plans repeatedly "
           "surprised by them.",
        structure="主干：Firms … will find their capital plans surprised ｜ 定语从句：that treat these as externalities ｜ "
                  "find + 宾语 + 过去分词补足语（宾补结构）",
        zh="把这些当作外部性的公司，会发现自己的资本计划一再被它们打乱。",
    ),
]


# ---------------------------------------------------------------------------
# 组装与落盘
# ---------------------------------------------------------------------------


def build_article(
    *,
    article_id: str,
    title: str,
    source: str,
    source_id: str,
    author: str,
    published_at: str,
    original_url: str,
    tags: list[str],
    difficulty: Difficulty,
    score: float,
    paragraphs: list[tuple[str, str]],
    vocab: list[VocabItem],
    sentences: list[SentenceAnalysis],
    summary_zh: str,
    takeaways: list[str],
    background: str,
    structure: str,
) -> ParsedArticle:
    pairs = [ParagraphPair(index=i, en=en.strip(), zh=zh.strip()) for i, (en, zh) in enumerate(paragraphs)]
    word_count = sum(len([w for w in p.en.replace("—", " ").split() if any(c.isalpha() for c in w)]) for p in pairs)
    return ParsedArticle(
        id=article_id,
        url_hash=url_hash(original_url),
        title=title,
        source=source,
        source_id=source_id,
        author=author,
        published_at=published_at,
        original_url=original_url,
        cover_image="",
        tags=tags,
        difficulty=difficulty,
        word_count=word_count,
        read_time_min=read_time_minutes(word_count),
        score=score,
        audio_url="",
        parsed_at=iso_now(),
        parser_mode="llm",
        overview=ArticleOverview(
            summary_zh=summary_zh,
            takeaways=takeaways,
            background=background,
            structure=structure,
        ),
        paragraphs=pairs,
        vocab=vocab,
        sentences=sentences,
    )


def main() -> int:
    storage = Storage()

    articles = [
        build_article(
            article_id="2026-11-23-aeon-the-architecture-of-attention",
            title="The Architecture of Attention",
            source="Aeon",
            source_id="aeon",
            author="Jane Doe",
            published_at="2026-11-23",
            original_url="https://aeon.co/essays/the-architecture-of-attention",
            tags=["Psychology", "Culture", "Design"],
            difficulty=Difficulty.C1,
            score=9.4,
            paragraphs=AEON_PARAGRAPHS,
            vocab=AEON_VOCAB,
            sentences=AEON_SENTENCES,
            summary_zh="注意力并非个人意志的产物，而是被房间、日程与默认设置共同建造出来的公共资源。"
                       "作者借阅览室的历史说明：静默之所以生产专注，是因为它让分心在社会层面变得昂贵；"
                       "而数字环境恰恰把这一逻辑颠倒过来。",
            takeaways=[
                "注意力是“建筑性”的：空间与制度安排塑造了专注的可能性，而非仅仅依赖意志力。",
                "注意力公地可以被圈占、耗竭，也可以被有意修复——关键在于默认设置。",
                "可靠的干预往往最不光鲜：关上的门、放在另一间屋子的设备、无人期待回复的一小时。",
            ],
            background="Aeon 长期刊发跨学科思想随笔，本文属其“注意力与数字生活”专题，"
                       "写作语境是过去十年关于注意力经济的公共讨论。",
            structure="现象切入（历史上的注意力）→ 概念转折（货币化隐喻的代价）→ 建筑学论证（阅览室案例）→ "
                      "反转（数字环境）→ 实践推论 → 社会层面的追问。",
        ),
        build_article(
            article_id="2026-11-22-quanta-the-constraint-that-replaced-a-paradox",
            title="The Constraint That Replaced a Paradox",
            source="Quanta Magazine",
            source_id="quanta",
            author="Daniel Moreau",
            published_at="2026-11-22",
            original_url="https://www.quantamagazine.org/the-constraint-that-replaced-a-paradox/",
            tags=["Physics", "Quantum", "Philosophy of Science"],
            difficulty=Difficulty.C2,
            score=9.1,
            paragraphs=QUANTA_PARAGRAPHS,
            vocab=QUANTA_VOCAB,
            sentences=QUANTA_SENTENCES,
            summary_zh="贝尔不等式把一个哲学争论变成了可由实验裁定的问题，而实验的结果并没有留下悖论，"
                       "只留下一道约束：实在论、决定论与定域性不能同时成立。"
                       "这道约束如今直接支撑着量子密码、量子计算与计量学。",
            takeaways=[
                "贝尔的贡献不在数学难度，而在把形而上学的分歧翻译成可执行的实验方案。",
                "被排除的不是实在论或决定论本身，而是它们与定域性的三者合取。",
                "一旦纠缠成为工程材料，哲学结论就开始承担技术功能。",
            ],
            background="本文回应的是近年来“贝尔实验无漏洞化”与量子技术工程化两条线索的交汇，"
                       "Quanta 的报道风格倾向于把数学结论还原为可叙述的推理过程。",
            structure="历史起点（1964 年贝尔论文）→ 方法论评价（为何重要）→ 实验结果 → 概念澄清 → "
                      "学界态度 → 技术回响。",
        ),
        build_article(
            article_id="2026-11-21-mit-tr-power-is-the-new-bottleneck",
            title="Power Is the New Bottleneck",
            source="MIT Technology Review",
            source_id="mit-tech-review",
            author="Priya Raman",
            published_at="2026-11-21",
            original_url="https://www.technologyreview.com/2026/11/21/power-is-the-new-bottleneck/",
            tags=["Technology", "Infrastructure", "Energy"],
            difficulty=Difficulty.C1,
            score=8.7,
            paragraphs=MIT_PARAGRAPHS,
            vocab=MIT_VOCAB,
            sentences=MIT_SENTENCES,
            summary_zh="数据中心的成本结构正在发生位移：瓶颈从硅片转移到电力与并网。"
                       "决定项目成败的变量，越来越多地落在围墙之外——电网改革速度、选址政治与电气劳动力供给。",
            takeaways=[
                "设施用电抵达处理器的比例，是比资本开支更能说明效率的指标。",
                "低效往往源于采购与设计假设，而非工程能力不足。",
                "并网排队已成为最具决定性的约束，且并非简单先到先得。",
            ],
            background="MIT Technology Review 的基建类报道，背景是全球算力扩张与电网投资周期错配，"
                       "以及小型模块化反应堆与燃气轮机重新进入选址讨论。",
            structure="以数字切入（能效比例）→ 归因（采购假设）→ 瓶颈迁移 → 并网队列 → 就地发电的合理性 → 战略含义。",
        ),
    ]

    for article in articles:
        path = storage.export_parsed_article(article)
        storage.set_parsed_path(article.id, str(path), status="published")
        print(f"  ✓ {article.id}  ({article.word_count} words, {len(article.vocab)} vocab, {len(article.sentences)} sentences)")

    sync = storage.sync_git_assets_to_db()
    print(f"\nindex.json 现有 {len(storage.load_index())} 篇；同步统计 {sync}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
