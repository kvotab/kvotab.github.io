[~,~,rawiso] = xlsread('rndecaydata.xlsx','Isotopes');
[~,~,rawel] = xlsread('rndecaydata.xlsx','Elements');
%
decaydata = sprintf('var decaydata = [\n');
for i=2:size(rawiso,1)
    decaydata = sprintf('%s\t{name:"%s",\n',decaydata,rawiso{i,1});             % Rn-XXX:{
    decaydata = sprintf('%s\tZ:%d,\n',decaydata,rawiso{i,2});       % Mass:XXX,
    decaydata = sprintf('%s\tA:%d,\n',decaydata,rawiso{i,3});       % Mass:XXX,
    decaydata = sprintf('%s\tElement:"%s",\n',decaydata,rawiso{i,4});       % Mass:XXX,
    %if isempty(raw{i,5})
        decaydata = sprintf('%s\tstate:"%s",\n',decaydata,rawiso{i,5}); 
    %else
    %    decaydata = sprintf('%s\tstate:"",\n',decaydata);
        
    %end
    decaydata = sprintf('%s\tid:%d,\n',decaydata,rawiso{i,6});       % Mass:XXX,
    decaydata = sprintf('%s\tMass:%.9f,\n',decaydata,rawiso{i,7});       % Mass:XXX,
    if strcmp(rawiso{i,11},'stable ')   
        decaydata = sprintf('%s\tHalflife:"Stable",\n',decaydata);   % Halflife:XXX,   
    else
        decaydata = sprintf('%s\tHalflife:"%s",\n',decaydata,rawiso{i,11});   % Halflife:XXX,
        decaydata = sprintf('%s\tHalflife_y:%d,\n',decaydata,rawiso{i,8}); % Halflife_y:XXX,
        decaydata = sprintf('%s\tAlpha_energy:%d,\n',decaydata,rawiso{i,24}); % Halflife_y:XXX,
        decaydata = sprintf('%s\tElectron_energy:%d,\n',decaydata,rawiso{i,25}); % Halflife_y:XXX,
        decaydata = sprintf('%s\tPhoton_energy:%d,\n',decaydata,rawiso{i,26}); % Halflife_y:XXX,
        decaydata = sprintf('%s\tDCC_ing:%d,\n',decaydata,rawiso{i,27}); % Halflife_y:XXX,
        decaydata = sprintf('%s\tDCC_ext:%d,\n',decaydata,rawiso{i,28}); % Halflife_y:XXX,
        decaydata = sprintf('%s\tProgenies:[\n',decaydata);
        base = 11;
        for j=1:4
           if isnan(rawiso{i,base+j})
               break;
           else
               mode = strrep(strrep(rawiso{i,base+8+j},'α','&alpha;'),'β','&beta;');
               decaydata = sprintf('%s\t\t{name:"%s",br:%d,mode:"%s"},\n',decaydata,rawiso{i,base+j},rawiso{i,base+4+j},mode);
           end
        end
        decaydata = sprintf('%s\t]\n',decaydata);
    end
        decaydata = sprintf('%s\t},\n',decaydata); 
end
decaydata = sprintf('%s];',decaydata); 

fid=fopen('rndecaydata.js','w');
fprintf(fid,decaydata);
fclose(fid);
%
[~,~,raw] = xlsread('rndecaydata.xlsx','Sheet4');
raw = cellfun(@num2str,raw(2:119,:),'UniformOutput',false);
raw = cellfun(@(x)strrep(x,'"',''''),raw,'UniformOutput',false);

Z = [rawiso{2:end,2}];
ID = [rawiso{2:end,6}];
datatree = sprintf('datatree = [\n');
%names = rawel(2:119,4);
%types = rawel(2:119,13);
for z=1:118        
    datatree = sprintf('%s\t{"text":"%s",type:"%s",a_attr:{"Z":"%s","type":"%s","symbol":"%s","block":"%s","origin_name":"%s","weight":"%s","density":"%s","melting":"%s","boiling":"%s","heat":"%s","electro":"%s","abundance":"%s","origin":"%s","phase":"%s","earth":"%s","electron":"%s","year":"%s","discoverer":"%s","note":"%s","radius":"%s","affin":"%s","oxi":"%s","ion":"%s","info":"%s"},children:[\n',...
        datatree,...
        raw{z,3},... name
        strrep(strrep(raw{z,20},'-','__'),' ','_'),... Type
        raw{z,1},... Z
        raw{z,20},... Type
        raw{z,2},... Symbol
        raw{z,7},... Block
        raw{z,4},... Origin of name
        raw{z,8},... weight
        raw{z,9},... density
        raw{z,10},... melting
        raw{z,11},... boiling
        raw{z,12},... heat
        raw{z,13},... electro
        raw{z,14},... abundance
        raw{z,15},... origin
        raw{z,16},... phase
        raw{z,17},... earth
        regexprep(raw{z,19},'([a-zA-Z]+)([0-9]+)','$1<sup>$2</sup>'),... electron
        raw{z,21},... year
        raw{z,22},... discoverer
        raw{z,23},... note
        raw{z,24},... radius
        raw{z,25},... electroaffinity
        raw{z,26},... oxidationstates
        raw{z,27},... ionization energy
        raw{z,28}... ionization energy
        );
    zInd = find(z==Z);
    [~,sortInd] = sort(ID(zInd));
    for i=1:length(zInd)
        row = 1+zInd(sortInd(i));
        if strcmp(rawiso{row,11},'stable ')   
           % datatree = sprintf('%s\t\t{"text":"%s",type:"isotope"},\n',datatree,rawiso{row,1});
        else
            datatree = sprintf('%s\t\t{"text":"%s",type:"radioisotope"},\n',datatree,rawiso{row,1});
        end
    end
    datatree = sprintf('%s\t]},\n',datatree);
end
datatree = sprintf('%s];',datatree);

fid=fopen('rndatatree.js','w');
fprintf(fid,datatree);
fclose(fid);
