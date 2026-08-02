# Scientific presentation template research

- Date: 2026-08-03
- Scope: Work SmarterのMarp technical report用`scientific` visual template

## Outcome

科学技術報告で広く使われるmessage hierarchy、余白、単純な配色、中央のvisual evidenceをMarp CSSへ
落とし込む。既存組織のbrandやtemplateそのものは複製せず、公開されているdesign guidanceの共通原則を採用する。

## Facts

- MIT AeroAstroは、左から右・上から下へ読むvisual hierarchy、簡潔なtitle、figureの単純化を推奨する。
- MIT ChemEは、黒・灰色と1つのaccent color、揃った要素、限られたfont size、十分なwhite spaceを推奨する。
- Harvard T.H. Chanは、sentence headline、visual evidence、white space、28pt以上のheadlineと18–24ptの本文を
  checklistにしている。
- NYUはvisual hierarchyの目安としてH1 36–44pt、H2 28–36pt、H3 24–28pt、本文18–24ptを示す。
- Northwesternは1 slide 1 message、単純なdiagram、graph/tableのannotationを推奨する。
- Marpitはglobal `style` directiveをdocument frontmatterで受け付ける。

## Considered paths

### Marpのbuilt-in themeだけを使う

dependencyは最小だが、title位置、見出し階層、図表中央配置をWork Smarterのcontractとして固定できない。

### standalone custom themeをMarp CLIへ登録する

複数documentで共有しやすい一方、`--theme-set`やcompiler configが必要になり、生成物だけでは再現できない。

### workspace CSSをdocumentの`style`へinline化する

userが編集でき、生成物がself-containedになる。CSSが各生成物へ複製されるが、local-firstの可搬性を優先して
この方法を採用する。

## Applied inferences

- titleと各slide headingは上端に固定し、視線の開始位置を安定させる。
- H1/H2/H3は52/44/36px（約39/33/27pt）、本文28px（約21pt）とし、3段の明確なhierarchyを作る。
- captionは20px（約15pt）、表は22px、複数表は20pxとし、補助情報も投影時に読める下限を保つ。
- white/near-white背景、濃色文字、blue accent 1色を基本にする。
- image、SVG、tableを水平方向の中央へ置き、figure captionも中央揃えにする。
- unordered listの3階層を`■`/`●`/`▲`で明示し、indentとshapeの両方でhierarchyを示す。
- list本文は32/28/24px（約24/21/18pt）とし、shape、indent、sizeの3要素でhierarchyを示す。
- 複数表はwide tableにも対応しやすい縦配置とし、2枚以上の場合だけ文字と余白をcompact化する。
- 箇条書き、visual evidence、caption、最後のLEADをsource順に配置し、LEADは28px、角丸14pxのtakeaway boxにする。
- templateは`Conclusion:`等のlabelを自動生成せず、authorが`**...**`で選んだ語句だけを本文色の太字にする。
- bodyを自動縮小せず、overflow時はcontent編集で1 slide 1 messageへ戻す。

## Verification

- Marp CLIで11 slidesのHTML sampleを生成した。
- browser computed styleでH1/H2/H3が52/44/36px、図と表のcenter deltaが0pxであることを確認した。
- titleがvertical centerになった初回sampleを発見し、`align-content: start`で上端配置へ修正した。
- 3-level listのmarkerを`■`/`●`/`▲`、indentを31/61/90pxとしてbrowserで確認した。
- 図、図番号、2つの表、2つの表番号のcenter deltaがすべて0px、slide overflowが0pxであることを確認した。
- list→figure→caption→LEADの順序、list 32/28/24px、LEAD 28px、slide overflow 0pxを確認した。
- explicit strongが本文色のweight 800、LEADが14px radiusと2px inset outlineであることを確認した。

## Unknowns

- projector、会議室display、印刷PDFでの色再現性はUNKNOWN。
- dense tableや縦長figureの自動分割が必要かはUNKNOWN。
- 3枚以上の表、wide table、長いcaptionを自動的に別slideへ分ける必要性はUNKNOWN。
- organization固有brand、logo、confidentiality footerの要件はUNKNOWN。

## Sources

- [MIT AeroAstro: Slide Design](https://mitcommlab.mit.edu/aeroastro/commkit/slide-design/)
- [MIT ChemE: Slideshow](https://mitcommlab.mit.edu/cheme/commkit/slideshow/)
- [Harvard T.H. Chan: Slide Design Checklist](https://hsph.harvard.edu/research/health-communication/resources/slide-checklist/)
- [NYU Stern: Visual Hierarchy](https://www.stern.nyu.edu/portal-partners/faculty-staff/learning-science-lab/learning-design/design-principles/communication)
- [Northwestern CLIMB: Designing PowerPoint Slides](https://www.northwestern.edu/climb/resources/oral-communication-skills/designing-PowerPoint-slides.html)
- [Marpit directives](https://marpit.marp.app/directives?id=backgrounds)
- [Marp CLI custom themes](https://github.com/marp-team/marp-cli/blob/main/README.md)
