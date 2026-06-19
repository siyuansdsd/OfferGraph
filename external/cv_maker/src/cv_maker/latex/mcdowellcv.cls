%% The MIT License (MIT)
%%
%% Copyright (c) 2015 Daniil Belyakov
%%
%% Permission is hereby granted, free of charge, to any person obtaining a copy
%% of this software and associated documentation files (the "Software"), to deal
%% in the Software without restriction, including without limitation the rights
%% to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
%% copies of the Software, and to permit persons to whom the Software is
%% furnished to do so, subject to the following conditions:
%%
%% The above copyright notice and this permission notice shall be included in all
%% copies or substantial portions of the Software.
%%
%% THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
%% IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
%% FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
%% AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
%% LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
%% OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
%% SOFTWARE.
\ProvidesClass{mcdowellcv}[2022/03/18 v1.2.0 McDowell CV class]

\def\mainfontsize{11pt}
\def\mainfontface{Times New Roman}

\DeclareOption{calibri}{%
  \def\mainfontface{Calibri}
}

\def\papersize{letterpaper}
\newif\ifpapersize

\DeclareOption{a4paper}{%
  \def\papersize{a4paper}
  \papersizetrue
}
\DeclareOption{letterpaper}{%
  \def\papersize{letterpaper}
  \papersizefalse
}
\ProcessOptions\relax

\LoadClass[\papersize,\mainfontsize]{article}

\usepackage[left=0.75in,top=0.6in,right=0.75in,bottom=0.6in]{geometry}
\usepackage{fontspec}
\setmainfont[SmallCapsFeatures={Renderer=Basic},
Ligatures={TeX, NoCommon, NoDiscretionary}]{\mainfontface}
\usepackage[parfill]{parskip}
\usepackage{array}
\usepackage{etoolbox}
\pagestyle{empty}
\usepackage{tabu}
\usepackage{changepage}
\usepackage{enumitem}
\setlist{leftmargin=*, noitemsep, topsep=-1\parskip}
\usepackage{ifthen}
\usepackage{ifplatform}
\usepackage{ifxetex}
\ifxetex
  \newcommand{\textls}[2][]{#2}
\else
  \usepackage{microtype}
  \DeclareMicrotypeSet*{smallcapsi} {
    encoding = {OT1,T1,T2A,LY1,OT4,QX,T5,TS1,EU1,EU2},
    shape = {sc*,si,scit}
  }
\fi

\ifthenelse{\equal{\platformname}{\notwindowsname}}{
  \def\namespaceskip{0.575em}
  \def\afterheaderspace{1.1pt}
  \def\beforesectionheaderspace{5pt}
  \def\sectionheadermargin{6pt}
  \def\beforesectionheaderhrulespace{2.85pt}
  \def\sectionheaderhrlueheight{0.518pt}
  \def\aftersectionheaderspace{-5.8pt}

  \ifpapersize
    \def\aftersinglelinesubsectionheaderspace{-5.75pt}
  \else
    \def\aftersinglelinesubsectionheaderspace{-20.25pt}
  \fi
  \def\afterdoublelinesubsectionheaderspace{-11.75pt}
  \def\aftermultilinesubsectionheaderspace{-7.75pt}
  \def\afteremptysubsectionheaderspace{1.25pt}
  \def\subsectionmargin{9pt}
  \def\aftersubsectionspace{2.1pt}
}{
  \def\namespaceskip{0.4em}
  \def\afterheaderspace{3pt}
  \def\beforesectionheaderspace{4.75pt}
  \def\sectionheadermargin{6pt}
  \def\beforesectionheaderhrulespace{3pt}
  \def\sectionheaderhrlueheight{0.5pt}
  \def\aftersectionheaderspace{-4pt}
  \ifpapersize
    \def\aftersinglelinesubsectionheaderspace{-4pt}
  \else
    \def\aftersinglelinesubsectionheaderspace{-18.5pt}
  \fi

  \def\afterdoublelinesubsectionheaderspace{-10pt}
  \def\aftermultilinesubsectionheaderspace{-6pt}
  \def\afteremptysubsectionheaderspace{3pt}
  \def\subsectionmargin{9pt}
  \def\aftersubsectionspace{4pt}
}

\makeatletter
\newcommand\address[1]{\def\@address{#1}}
\address{}
\newcommand\printaddress{
  \small{\@address}
}
\makeatother

\makeatletter
\newcommand\name[1]{\def\@name{#1}}
\name{}
\newcommand\printname{
  \spaceskip \namespaceskip \relax
  \textbf{\LARGE\textls[110]{\textsc{\@name}}}
}
\makeatother

\makeatletter
\newcommand\contacts[1]{\def\@contacts{#1}}
\contacts{}
\newcommand\printcontacts{
  \small{\@contacts}
}
\makeatother

\makeatletter
\newcommand\makeheader{
  \begin{center}
    \begin{tabu} to 1\textwidth { X[l,m] X[1.7,c,m] X[1.3,r,m] }
      \printaddress & \printname & \printcontacts \\
    \end{tabu}
  \end{center}
  \vspace*{\afterheaderspace}
}
\makeatother

\makeatletter
\newenvironment{cvsection}[1]{
  \vspace*{\beforesectionheaderspace}
  \begin{adjustwidth}{\sectionheadermargin}{\sectionheadermargin}
    \textsc{\textbf{#1}}
  \end{adjustwidth}
  \vspace*{\beforesectionheaderhrulespace}
  \hrule height \sectionheaderhrlueheight
  \vspace*{\aftersectionheaderspace}
}{}
\makeatother

\makeatletter
\newtoggle{lefttitledefined}
\newtoggle{centertitledefined}
\newtoggle{righttitledefined}
\newenvironment{cvsubsection}[4][1]{
  \notblank{#2}{\toggletrue{lefttitledefined}}{}
  \notblank{#3}{\toggletrue{centertitledefined}}{}
  \notblank{#4}{\toggletrue{righttitledefined}}{}
  \ifboolexpr{togl {lefttitledefined} or togl {centertitledefined} or togl {righttitledefined}}{
    \begin{tabu} to 1\textwidth { X[l,p] X[c,p] X[r,p] }
      \textbf{#2} & \textbf{#3} & \textbf{#4} \\
    \end{tabu}
    \ifnumcomp{#1}{=}{1}{\vspace*{\aftersinglelinesubsectionheaderspace}}{
      \ifnumcomp{#1}{=}{2}{\vspace*{\afterdoublelinesubsectionheaderspace}}{
        \vspace*{\aftermultilinesubsectionheaderspace}
      }
    }
  }{
    \vspace*{\afteremptysubsectionheaderspace}
  }
  \togglefalse{lefttitledefined}
  \togglefalse{centertitledefined}
  \togglefalse{righttitledefined}
  \begin{adjustwidth}{\subsectionmargin}{\subsectionmargin}
}
{
  \end{adjustwidth}
  \vspace*{\aftersubsectionspace}
}
\makeatother
