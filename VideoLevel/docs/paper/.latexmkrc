# Build the manuscript with pdfLaTeX. The T5 (Vietnamese) font encoding set in
# main.tex, backed by vntex's T5 Times/Helvetica/Courier, renders the Vietnamese
# diacritics. latexmk runs bibtex and reruns passes until references resolve.
#   latexmk -pdf main.tex
$pdf_mode = 1;
$pdflatex = 'pdflatex -interaction=nonstopmode -synctex=1 %O %S';
$bibtex_use = 2;
