from pathlib import Path
import json, re, sys

root = Path(sys.argv[1]).resolve()
app = root / "app" / "KBL_COLETOR.ps1"
catalog_path = root / "collectors" / "catalog.json"
version_path = root / "version.json"
hub_path = root / "hub_app.json"

src = app.read_text(encoding="utf-8-sig")
if "$Version = '2.4.8'" not in src:
    raise SystemExit("Base esperada v2.4.8 não encontrada.")
src = src.replace("$Version = '2.4.8'", "$Version = '2.4.9'", 1)

# ---------------------------------------------------------------------
# 1) Isolar TODA a automação ao processo/módulo correto do Domínio.
# ---------------------------------------------------------------------
start = src.find("function Get-DominioWindows {")
end = src.find("function Match-Any", start)
if start < 0 or end < 0:
    raise SystemExit("Get-DominioWindows/Get-DominioMainWindow não encontrados.")

new_windows = r"""function Get-DominioModulePattern([string]$ModuleKey='') {
    switch(([string]$ModuleKey).ToLowerInvariant()){
        'contabilidade' { return 'Contab' }
        'fiscal'        { return 'Escrita Fiscal|Fiscal' }
        'folha'         { return 'Folha' }
        'patrimonio'    { return 'Patrim' }
        default         { return '' }
    }
}

function Get-DominioMainWindow([string]$ModuleKey='') {
    if([string]::IsNullOrWhiteSpace($ModuleKey) -and -not [string]::IsNullOrWhiteSpace([string]$script:ActiveDominioModule)){
        $ModuleKey=[string]$script:ActiveDominioModule
    }

    $modulePattern=Get-DominioModulePattern $ModuleKey
    $best=$null

    foreach($w in (Get-AllTopWindows)){
        try {
            $n=[string]$w.Current.Name
            if($n -notmatch 'Dom[ií]nio'){continue}

            if(-not [string]::IsNullOrWhiteSpace($modulePattern) -and $n -match $modulePattern){
                return $w
            }
            if($null -eq $best){$best=$w}
        } catch {}
    }
    return $best
}

function Get-DominioWindows([string]$ModuleKey='') {
    $all=@(Get-AllTopWindows)
    $main=$null
    try{$main=Get-DominioMainWindow $ModuleKey}catch{}

    $dominioProcessId=0
    if($main){
        try{$dominioProcessId=[int]$main.Current.ProcessId}catch{$dominioProcessId=0}
    }
    if($dominioProcessId -le 0 -and [int]$script:ActiveDominioProcessId -gt 0){
        $dominioProcessId=[int]$script:ActiveDominioProcessId
    }

    $list=New-Object System.Collections.Generic.List[System.Windows.Automation.AutomationElement]
    foreach($w in $all){
        try {
            $windowProcessId=[int]$w.Current.ProcessId

            # Regra principal: se conhecemos o PID do Domínio, SOMENTE janelas
            # desse processo podem participar da automação.
            if($dominioProcessId -gt 0){
                if($windowProcessId -eq $dominioProcessId){$list.Add($w)}
                continue
            }

            # Fallback conservador: sem PID, aceitar apenas janela cujo próprio
            # título contenha "Domínio". Nunca aceitar "Relatório", "Excel" etc.
            $n=[string]$w.Current.Name
            if($n -match 'Dom[ií]nio'){$list.Add($w)}
        } catch {}
    }

    if($main){
        $mainHandle=0
        try{$mainHandle=[int]$main.Current.NativeWindowHandle}catch{}
        return @($list | Sort-Object {
            try {
                if([int]$_.Current.NativeWindowHandle -eq $mainHandle){1}else{0}
            } catch {1}
        })
    }
    return @($list)
}

"""
src = src[:start] + new_windows + src[end:]

# Connect-Dominio passa a memorizar módulo e PID corretos.
old_connect = """function Connect-Dominio($Profile) {
    Write-KblLog 'Localizando o Domínio...'
    $dom = Get-DominioMainWindow
    if ($null -eq $dom) { throw 'Domínio não encontrado. Abra o Domínio e entre no módulo correspondente.' }
"""
new_connect = """function Connect-Dominio($Profile,[string]$ModuleKey='') {
    Write-KblLog 'Localizando o Domínio...'
    $dom = Get-DominioMainWindow $ModuleKey
    if ($null -eq $dom) { throw 'Domínio não encontrado. Abra o Domínio e entre no módulo correspondente.' }

    $script:ActiveDominioModule=[string]$ModuleKey
    try{$script:ActiveDominioProcessId=[int]$dom.Current.ProcessId}catch{$script:ActiveDominioProcessId=0}
"""
if old_connect not in src:
    raise SystemExit("Connect-Dominio original não encontrado.")
src = src.replace(old_connect, new_connect, 1)

src = src.replace(
    "$dom = Connect-Dominio $Profile\n",
    "$dom = Connect-Dominio $Profile ([string]$Report.module)\n",
    1
)

# ---------------------------------------------------------------------
# 2) Período: nunca mais pegar "os primeiros Edit" da tela.
#    Localiza Data Inicial/Final pela legenda/contexto/geometria e CONFERE.
# ---------------------------------------------------------------------
start = src.find("function Set-ValuePattern(")
end = src.find("function Get-UiaAncestorText", start)
if start < 0 or end < 0:
    raise SystemExit("Set-ValuePattern/Set-ReportPeriod não encontrados.")

new_period = r"""function Get-UiaValueText([System.Windows.Automation.AutomationElement]$Element) {
    if($null -eq $Element){return ''}
    try {
        $vp=$Element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        return [string]$vp.Current.Value
    } catch {}
    try {
        $lp=$Element.GetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern)
        return [string]$lp.Current.Value
    } catch {}
    try { return [string]$Element.Current.Name } catch { return '' }
}

function Set-ValuePattern([System.Windows.Automation.AutomationElement]$Element,[string]$Value) {
    Test-StopRequested
    if($null -eq $Element){return $false}

    # 1) ValuePattern
    try {
        $vp=$Element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        $vp.SetValue($Value)
        return $true
    } catch {
        if($_.Exception.Message -eq 'KBL_STOP_REQUESTED'){throw}
    }

    # 2) Legacy IAccessible
    try {
        $lp=$Element.GetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern)
        $lp.SetValue($Value)
        return $true
    } catch {
        if($_.Exception.Message -eq 'KBL_STOP_REQUESTED'){throw}
    }

    # 3) Teclado, somente com foco explícito no próprio controle do Domínio.
    try {
        Remember-UserWorkWindow
        $Element.SetFocus()
        Sleep-Kbl 80
        [System.Windows.Forms.SendKeys]::SendWait('^a')
        Sleep-Kbl 50
        [System.Windows.Forms.SendKeys]::SendWait($Value)
        Sleep-Kbl 100
        if([bool]$script:Settings.background_mode){Restore-UserWorkWindow}
        return $true
    } catch {
        if([bool]$script:Settings.background_mode){Restore-UserWorkWindow}
        return $false
    }
}

function Normalize-UiaDateDigits([string]$Value) {
    if([string]::IsNullOrWhiteSpace($Value)){return ''}
    return (($Value -replace '[^\d]','').Trim())
}

function Test-UiaValueMatches([System.Windows.Automation.AutomationElement]$Element,[string]$Expected,[string]$Mode='date') {
    $actual=Get-UiaValueText $Element
    $a=Normalize-UiaDateDigits $actual
    $e=Normalize-UiaDateDigits $Expected

    if($Mode -eq 'date'){
        # ddMMyyyy
        return ($a -eq $e -or $a.EndsWith($e))
    }
    if($Mode -eq 'month'){
        # MMyyyy
        return ($a -eq $e -or $a.EndsWith($e))
    }
    return ($actual -eq $Expected)
}

function Get-NearbyUiaLabelText($Edit,[object[]]$Elements) {
    $labels=New-Object System.Collections.Generic.List[string]
    try {
        $er=$Edit.Current.BoundingRectangle
        if($er.Width -le 0 -or $er.Height -le 0){return ''}
        $ecy=$er.Top+($er.Height/2)

        foreach($x in $Elements){
            if($null -eq $x -or $x -eq $Edit){continue}
            try {
                $n=[string]$x.Current.Name
                if([string]::IsNullOrWhiteSpace($n)){continue}
                $ct=$x.Current.ControlType
                if($ct -ne [System.Windows.Automation.ControlType]::Text -and
                   $ct -ne [System.Windows.Automation.ControlType]::Group -and
                   $ct -ne [System.Windows.Automation.ControlType]::Custom){continue}

                $r=$x.Current.BoundingRectangle
                if($r.Width -le 0 -or $r.Height -le 0){continue}
                $cy=$r.Top+($r.Height/2)

                $leftOf=($r.Right -le ($er.Left+20) -and ($er.Left-$r.Right) -le 260 -and [Math]::Abs($cy-$ecy) -le 45)
                $above=($r.Bottom -le ($er.Top+10) -and ($er.Top-$r.Bottom) -le 65 -and
                        $r.Right -ge ($er.Left-30) -and $r.Left -le ($er.Right+30))
                if($leftOf -or $above){$labels.Add($n)}
            } catch {}
        }
    } catch {}
    return ($labels -join ' | ')
}

function Get-PeriodEditCandidates {
    $result=New-Object System.Collections.Generic.List[object]

    foreach($w in (Get-DominioWindows)){
        Test-StopRequested
        $elements=@(Get-UiaAll $w 380 7)

        foreach($el in $elements){
            try {
                if($el.Current.ControlType -ne [System.Windows.Automation.ControlType]::Edit){continue}
                if(-not $el.Current.IsEnabled -or $el.Current.IsOffscreen){continue}

                $name=[string]$el.Current.Name
                $aid=[string]$el.Current.AutomationId
                $ctx=Get-UiaAncestorText $el 5
                $near=Get-NearbyUiaLabelText $el $elements
                $full=("$name | $aid | $ctx | $near").Trim()

                $r=$el.Current.BoundingRectangle
                $result.Add([pscustomobject]@{
                    Element=$el
                    Text=$full
                    Name=$name
                    AutomationId=$aid
                    Left=[double]$r.Left
                    Top=[double]$r.Top
                })
            } catch {
                if($_.Exception.Message -eq 'KBL_STOP_REQUESTED'){throw}
            }
        }
    }

    return @($result)
}

function Score-PeriodEdit($Candidate,[string]$Role) {
    $text=[string]$Candidate.Text
    $score=0

    # Penaliza campos que tipicamente NÃO são datas.
    if($text -match 'Classifica|Classificação|Código|Codigo|Conta|Grupo|Livro|Página|Pagina|Modelo|Número|Numero|Folha|Ordem'){
        $score-=80
    }

    switch($Role){
        'initial' {
            if($text -match '(?i)Data\s*Inicial|Per[ií]odo\s*Inicial|Inicial'){ $score+=120 }
            if($text -match '(?i)\bDe\b|In[ií]cio'){ $score+=35 }
        }
        'final' {
            if($text -match '(?i)Data\s*Final|Per[ií]odo\s*Final|Final'){ $score+=120 }
            if($text -match '(?i)At[eé]'){ $score+=35 }
        }
        'competence' {
            if($text -match '(?i)Compet[eê]ncia'){ $score+=120 }
            if($text -match '(?i)Per[ií]odo'){ $score+=45 }
        }
    }

    if($text -match '(?i)\bData\b'){ $score+=25 }
    if($text -match '(?i)Per[ií]odo'){ $score+=20 }
    return $score
}

function Find-PeriodEdit([object[]]$Candidates,[string]$Role) {
    $ranked=@()
    foreach($c in $Candidates){
        $ranked += [pscustomobject]@{Candidate=$c;Score=(Score-PeriodEdit $c $Role)}
    }
    $best=$ranked | Sort-Object Score -Descending | Select-Object -First 1
    if($best -and [int]$best.Score -ge 60){return $best.Candidate}
    return $null
}

function Set-VerifiedPeriodValue($Candidate,[string]$Value,[string]$Mode) {
    if($null -eq $Candidate){return $false}
    $el=$Candidate.Element

    foreach($tryValue in @($Value,(Normalize-UiaDateDigits $Value))){
        Test-StopRequested
        if([string]::IsNullOrWhiteSpace($tryValue)){continue}
        [void](Set-ValuePattern $el $tryValue)
        Sleep-Kbl 100
        if(Test-UiaValueMatches $el $Value $Mode){return $true}
    }
    return $false
}

function Set-ReportPeriod($Report,$Period) {
    if([string]$Report.period_mode -eq 'none'){return $true}
    Test-StopRequested

    $start=$Period.Start
    if([string]$Report.period_mode -eq 'ytd'){
        $start=Get-Date -Year $Period.Year -Month 1 -Day 1
    }
    $end=$Period.End

    $candidates=@(Get-PeriodEditCandidates)
    if($candidates.Count -eq 0){
        throw "Tela do relatório abriu, mas nenhum campo de período editável foi identificado. A coleta foi interrompida para não emitir competência errada."
    }

    $initial=Find-PeriodEdit $candidates 'initial'
    $final=Find-PeriodEdit $candidates 'final'

    # Fallback conservador: somente campos cujo contexto menciona Data/Período.
    if($null -eq $initial -or $null -eq $final){
        $dateCandidates=@($candidates | Where-Object { $_.Text -match '(?i)\bData\b|Per[ií]odo' } | Sort-Object Top,Left)
        if($dateCandidates.Count -ge 2){
            if($null -eq $initial){$initial=$dateCandidates[0]}
            if($null -eq $final){$final=$dateCandidates[1]}
        }
    }

    if($initial -and $final -and $initial.Element -ne $final.Element){
        $sv=$start.ToString('dd/MM/yyyy')
        $ev=$end.ToString('dd/MM/yyyy')

        $ok1=Set-VerifiedPeriodValue $initial $sv 'date'
        $ok2=Set-VerifiedPeriodValue $final $ev 'date'
        if(-not $ok1 -or -not $ok2){
            $a=Get-UiaValueText $initial.Element
            $b=Get-UiaValueText $final.Element
            throw "Não consegui confirmar Data Inicial/Final. Esperado: $sv a $ev. Tela ficou: '$a' e '$b'. O relatório NÃO será gerado."
        }

        Write-KblLog ("Período confirmado na tela: $sv a $ev")
        return $true
    }

    # Relatórios que trabalham com competência única.
    $competence=Find-PeriodEdit $candidates 'competence'
    if($competence){
        $mv=$Period.Start.ToString('MM/yyyy')
        if(Set-VerifiedPeriodValue $competence $mv 'month'){
            Write-KblLog ("Competência confirmada na tela: $mv")
            return $true
        }
    }

    throw "Não consegui identificar e confirmar os campos corretos de período deste relatório. A coleta foi interrompida antes de clicar em OK."
}

"""
src = src[:start] + new_period + src[end:]

# ---------------------------------------------------------------------
# 3) Balancete: opções oficiais mínimas e previsíveis.
# ---------------------------------------------------------------------
needle = """    switch($id){
        'contabil_plano' {
"""
replacement = """    switch($id){
        'contabil_balancete' {
            Select-UiaNamedOption @('^Total$') @('Imprimir plano|Imprimir Plano') | Out-Null
            Write-KblLog 'Balancete: emissão do plano Total configurada.'
        }
        'contabil_plano' {
"""
if needle not in src:
    raise SystemExit("Switch Configure-OfficialReportOptions não encontrado.")
src = src.replace(needle, replacement, 1)

# ---------------------------------------------------------------------
# 4) Geração: botão EXATO do Domínio, janela atual, sem espera infinita.
# ---------------------------------------------------------------------
start = src.find("function Execute-ReportGeneration {")
end = src.find("function Find-SaveDialog", start)
if start < 0 or end < 0:
    raise SystemExit("Execute-ReportGeneration não encontrado.")

new_generation = r"""function Get-DominioWindowSnapshot {
    $items=New-Object System.Collections.Generic.List[string]
    foreach($w in (Get-DominioWindows)){
        try {
            $items.Add(('{0}|{1}' -f [int]$w.Current.NativeWindowHandle,[string]$w.Current.Name))
        } catch {}
    }
    return @($items)
}

function Click-ReportActionButton($Report) {
    $exact=@('OK','Gerar','Executar','Visualizar')
    foreach($w in (Get-DominioWindows)){
        Test-StopRequested
        foreach($el in (Get-UiaAll $w 320 7)){
            try {
                if($el.Current.ControlType -ne [System.Windows.Automation.ControlType]::Button){continue}
                if(-not $el.Current.IsEnabled -or $el.Current.IsOffscreen){continue}
                $name=([string]$el.Current.Name).Trim()
                if($exact -contains $name){
                    if(Invoke-UiaElement $el){
                        Write-KblLog ("Botão de geração acionado: '$name' | relatório=$([string]$Report.name)")
                        return $true
                    }
                }
            } catch {
                if($_.Exception.Message -eq 'KBL_STOP_REQUESTED'){throw}
            }
        }
    }
    return $false
}

function Execute-ReportGeneration($Report) {
    Test-StopRequested
    $before=@(Get-DominioWindowSnapshot)

    if(-not (Click-ReportActionButton $Report)){
        throw "Botão OK/Gerar/Executar/Visualizar do relatório '$([string]$Report.name)' não foi encontrado. A coleta foi interrompida."
    }

    # Aguarda no máximo 12 s por alguma mudança de janela/estado. A interface
    # continua processando eventos e o botão PARAR continua funcional.
    $sw=[Diagnostics.Stopwatch]::StartNew()
    $changed=$false
    while($sw.Elapsed.TotalSeconds -lt 12){
        Test-StopRequested
        Sleep-Kbl 200

        $after=@(Get-DominioWindowSnapshot)
        if(($after -join '||') -ne ($before -join '||')){
            $changed=$true
            break
        }

        # Se o diálogo de parâmetros sumiu ou ficou indisponível, também é
        # evidência de que o Domínio aceitou a geração.
        $hasEnabledEdit=$false
        foreach($w in (Get-DominioWindows)){
            foreach($el in (Get-UiaAll $w 120 5)){
                try {
                    if($el.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit -and
                       $el.Current.IsEnabled -and -not $el.Current.IsOffscreen){
                        $hasEnabledEdit=$true
                        break
                    }
                } catch {}
            }
            if($hasEnabledEdit){break}
        }
        if(-not $hasEnabledEdit){$changed=$true;break}
    }

    if(-not $changed){
        throw "O Domínio recebeu o comando para gerar '$([string]$Report.name)', mas nenhuma mudança foi confirmada em 12 segundos. A fila foi interrompida para evitar travamento."
    }

    Write-KblLog 'Geração confirmada pelo Domínio.'
    return $true
}

"""
src = src[:start] + new_generation + src[end:]

# Atualiza chamadas.
src = src.replace("Execute-ReportGeneration\n", "Execute-ReportGeneration $Report\n")

# ---------------------------------------------------------------------
# 5) Exportação: somente pasta temporária KBL e espera curta/cancelável.
# ---------------------------------------------------------------------
start = src.find("function Find-NewExportFile(")
end = src.find("function Set-CollectionStage", start)
if start < 0 or end < 0:
    raise SystemExit("Find-NewExportFile/Invoke-Export não encontrados.")

new_export = r"""function Find-NewExportFile([datetime]$Since,[string]$Extension,[string]$ApprovedRoot) {
    if([string]::IsNullOrWhiteSpace($ApprovedRoot) -or -not (Test-Path $ApprovedRoot)){return $null}

    try {
        $approved=[IO.Path]::GetFullPath((Resolve-Path $ApprovedRoot).Path)
        $owned=[IO.Path]::GetFullPath((Resolve-Path $TempDir).Path)
        $sep=[IO.Path]::DirectorySeparatorChar
        $ownedPrefix=$owned.TrimEnd($sep)+$sep
        $inside=$approved.Equals($owned,[StringComparison]::OrdinalIgnoreCase) -or
                $approved.StartsWith($ownedPrefix,[StringComparison]::OrdinalIgnoreCase)
        if(-not $inside){return $null}
    } catch {return $null}

    try {
        return Get-ChildItem $approved -File -Filter ('*.'+$Extension) -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $Since.AddSeconds(-1) } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    } catch {return $null}
}

function Invoke-Export([string]$Extension,[string]$TempPath) {
    Test-StopRequested
    $since=Get-Date

    try {
        $tempParent=Split-Path $TempPath -Parent
        if(-not (Test-Path $tempParent)){New-Item -ItemType Directory -Force -Path $tempParent | Out-Null}
        if(Test-Path $TempPath){Remove-Item $TempPath -Force -ErrorAction SilentlyContinue}
    } catch {}

    $patterns=if($Extension -eq 'pdf'){
        @('^PDF$','^Adobe PDF$','^Exportar PDF$','^Salvar PDF$')
    }else{
        @('^Excel$','^XLSX$','^Planilha$','^Exportar para Excel$','^Exportar Excel$')
    }

    $clicked=Click-AnyWindowByName $patterns 2500
    if(-not $clicked){
        $clicked=Click-AnyWindowByName @('^Exportar$','^Salvar$') 1200
        if($clicked){
            Sleep-Kbl 250
            $fmt=if($Extension -eq 'pdf'){@('^PDF$')}else{@('^Excel$','^XLSX$')}
            [void](Click-AnyWindowByName $fmt 1200)
            [void](Click-AnyWindowByName @('^OK$','^Exportar$','^Salvar$') 1000)
        }
    }

    if($clicked){
        if(Fill-SaveDialog $TempPath){
            $sw=[Diagnostics.Stopwatch]::StartNew()
            while($sw.Elapsed.TotalSeconds -lt 8){
                Test-StopRequested
                if(Test-Path $TempPath){return $TempPath}
                Sleep-Kbl 200
            }
        }
    }

    # Último fallback permitido: SOMENTE a própria pasta temporária KBL.
    $sw=[Diagnostics.Stopwatch]::StartNew()
    while($sw.Elapsed.TotalSeconds -lt 5){
        Test-StopRequested
        $f=Find-NewExportFile $since $Extension (Split-Path $TempPath -Parent)
        if($f){
            if([IO.Path]::GetFullPath($f.FullName) -ne [IO.Path]::GetFullPath($TempPath)){
                Copy-Item $f.FullName $TempPath -Force
            }
            return $TempPath
        }
        Sleep-Kbl 200
    }

    throw "O Domínio não confirmou a exportação .$Extension em até 13 segundos. Downloads, Desktop e Documentos não são usados como fonte."
}


"""
src = src[:start] + new_export + src[end:]

# ---------------------------------------------------------------------
# 6) Fila fail-fast: uma falha de automação para a fila inteira.
# ---------------------------------------------------------------------
old_max = """    $format = Get-ReportFormat $p $r
    $max = if([string]$r.module -eq 'folha'){1}elseif([string]$r.source_type -eq 'bgr'){1}else{[Math]::Max(1,[int]$script:Settings.retries)}
"""
new_max = """    $format = Get-ReportFormat $p $r
    # Enquanto o motor de automação está em modo seguro, uma tentativa por
    # relatório. Repetir cliques em tela errada só aumenta o risco.
    $max = 1
"""
if old_max not in src:
    raise SystemExit("Configuração de retries não encontrada.")
src = src.replace(old_max, new_max, 1)

# No final do Run-OneQueueEntry, marcar abort crítico.
needle = """    $Entry.status='Erro'
    $Entry.error=$lastError
    $hist=[pscustomobject]@{
"""
replacement = """    $Entry.status='Erro'
    $Entry.error=$lastError
    $script:AbortDueToAutomationError=$true
    $hist=[pscustomobject]@{
"""
if needle not in src:
    raise SystemExit("Final de erro da entrada não encontrado.")
src = src.replace(needle, replacement, 1)

# Inicializa flag.
src = src.replace(
    "$script:StopRequested=$false\n    $script:BgrAttempted=@{}\n",
    "$script:StopRequested=$false\n    $script:AbortDueToAutomationError=$false\n    $script:BgrAttempted=@{}\n",
    1
)

# Para a fila logo após o primeiro erro.
old_after_entry = """            if ($e.status -eq 'Erro') { $errors++ }
            $done++
            $Queue.updated_at=(Get-Date).ToString('o')
            Save-Queue $Queue
"""
new_after_entry = """            if ($e.status -eq 'Erro') {
                $errors++
                $done++
                $Queue.updated_at=(Get-Date).ToString('o')
                Save-Queue $Queue
                Write-KblLog 'Fila interrompida após a primeira falha de automação para evitar travamento/repetição.'
                break
            }
            $done++
            $Queue.updated_at=(Get-Date).ToString('o')
            Save-Queue $Queue
"""
if old_after_entry not in src:
    raise SystemExit("Pós-execução da fila não encontrado.")
src = src.replace(old_after_entry, new_after_entry, 1)

# Estado final correto.
old_final_branch = """        if([bool]$script:StopRequested){
            $Queue.state='Interrompida pelo usuário'
"""
new_final_branch = """        if([bool]$script:StopRequested){
            $Queue.state='Interrompida pelo usuário'
"""
# branch stays, insert elseif before existing else
needle2 = """            Notify-Kbl 'KBL COLETOR' "Coleta parada. Concluídos: $done de $total. Você pode retomar depois."
        } else {
            $Queue.state= if ($errors -gt 0) { 'Concluída com erros' } else { 'Concluída' }
"""
replacement2 = """            Notify-Kbl 'KBL COLETOR' "Coleta parada. Concluídos: $done de $total. Você pode retomar depois."
        } elseif([bool]$script:AbortDueToAutomationError) {
            $Queue.state='Interrompida por erro'
            $Queue.updated_at=(Get-Date).ToString('o')
            Save-Queue $Queue
            Write-RuntimeStatus 'Erro' "Fila interrompida após erro de automação. Concluídos: $done/$total." $done $total $errors
            Append-AuditTrail 'queue_abort_error' "$done/$total; erros=$errors"
            Notify-Kbl 'KBL COLETOR' 'A coleta foi interrompida no primeiro erro para não travar nem clicar em telas erradas.'
        } else {
            $Queue.state= if ($errors -gt 0) { 'Concluída com erros' } else { 'Concluída' }
"""
if needle2 not in src:
    raise SystemExit("Branch final da fila não encontrado.")
src = src.replace(needle2, replacement2, 1)

# ---------------------------------------------------------------------
# 7) Diagnóstico e metadados.
# ---------------------------------------------------------------------
for p in (version_path, hub_path):
    obj=json.loads(p.read_text(encoding="utf-8-sig"))
    obj["version"]="2.4.9"
    if p == hub_path:
        obj["description"]="Coleta no Domínio com período validado, automação isolada ao processo correto e fila fail-fast."
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")

catalog=json.loads(catalog_path.read_text(encoding="utf-8-sig"))
for r in catalog:
    if r.get("official_menu_path"):
        r["period_engine"]="labeled-verified"
        r["automation_mode"]="fail-fast"
catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding="utf-8")

app.write_text(src,encoding="utf-8-sig")

# Validações estáticas.
final=app.read_text(encoding="utf-8-sig")
checks={
    "version": final.count("$Version = '2.4.9'"),
    "Set-ReportPeriod": len(re.findall(r"(?m)^function Set-ReportPeriod\b",final)),
    "Execute-ReportGeneration": len(re.findall(r"(?m)^function Execute-ReportGeneration\b",final)),
    "Get-DominioWindows": len(re.findall(r"(?m)^function Get-DominioWindows\b",final)),
    "Get-DominioMainWindow": len(re.findall(r"(?m)^function Get-DominioMainWindow\b",final)),
}
for k,v in checks.items():
    if v != 1:
        raise SystemExit(f"{k} aparece {v}x; esperado 1.")

for forbidden in [
    "Join-Path $env:USERPROFILE 'Downloads'",
    "Join-Path $env:USERPROFILE 'Desktop'",
    "Join-Path $env:USERPROFILE 'Documents'",
]:
    if forbidden in final:
        raise SystemExit(f"Pasta pessoal ainda usada na exportação: {forbidden}")

if "Nenhum campo de período identificado nesta tela; seguindo sem alterar." in final:
    raise SystemExit("Ainda existe fallback silencioso de período.")
if re.search(r"(?i)\$pid\s*=",final):
    raise SystemExit("Regressão $PID.")

print("PATCH_OK KBL COLETOR 2.4.9")
print(json.dumps(checks,indent=2))
