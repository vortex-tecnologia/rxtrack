// admin_pagador.js - Auto-preenchimento do CNPJ ao selecionar o Pagador no Django Admin
(function() {
    function initPagadorAutoFill() {
        document.addEventListener('change', function(e) {
            if (e.target && (e.target.classList.contains('select-pagador-dropdown') || (e.target.name && e.target.name.indexOf('pagador_nome') !== -1))) {
                const select = e.target;
                if (!select.options || select.selectedIndex < 0) return;
                
                const selectedText = select.options[select.selectedIndex].text;
                // Procura CNPJ ou CPF entre parênteses no final da label: "EMPRESA S/A (12.345.678/0001-90)"
                const match = selectedText.match(/\(([^)]+)\)$/);
                const cnpj = match ? match[1].trim() : '';

                // Procura na mesma linha da tabela (Inline) ou no mesmo form-row (ModelAdmin)
                const container = select.closest('tr') || select.closest('.form-row') || select.closest('fieldset');
                if (container) {
                    const docInput = container.querySelector('input[name$="-pagador_documento"], input[name="pagador_documento"]');
                    if (docInput && cnpj) {
                        docInput.value = cnpj;
                        docInput.dispatchEvent(new Event('input', { bubbles: true }));
                        docInput.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPagadorAutoFill);
    } else {
        initPagadorAutoFill();
    }
})();
