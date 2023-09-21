
var COLORS = [[31, 119, 180],[	255, 127, 14],[44, 160, 44],[214, 39, 40],[148, 103, 189],[140, 86, 75],[227, 119, 194],[127, 127, 127],[188, 189, 34],[23, 190, 207]];
var LINES = ["solid", "dash", "dot", "dashdot"];
var TYPE_STABLE = 0;
var TYPE_NUCLIDE = 1;
var TYPE_SF = 2;
var TOTALACTIVITY = 0;
var CHARTDIALOG = $("#chartdialog");
var YAXISTYPE = 'linear';
var XAXISTYPE = 'log';
$(function () {
    $.widget("custom.catcomplete", $.ui.autocomplete, {
        _create: function () {
            this._super();
            this.widget().menu("option", "items", "> :not(.ui-autocomplete-category)");
        },
        _renderMenu: function (ul, items) {
            var that = this,
            currentCategory = "";
            $.each(items, function (index, item) {
                var li;
                if (item.category != currentCategory) {
                    ul.append("<li class='ui-autocomplete-category'>" + item.category + "</li>");
                    currentCategory = item.category;
                }
                li = that._renderItemData(ul, item);
                if (item.category) {
                    li.attr("aria-label", item.category + " : " + item.label);
                }
            });
        }
    });
    var rns = [];
    var count = 0;
    for (let i = 0; i < datatree.length; i++) {

        for (let j = 0; j < datatree[i].children.length; j++) {
            rns[count] = {
                label: datatree[i].children[j].text,
                category: datatree[i].text
            };
            count = count + 1;
        }
    }
    // Add the elements
    for (let i = 0; i < datatree.length; i++) {

        rns[count] = {
            label: datatree[i].text,
            category: "Element"
        };
        count = count + 1;
    }
    $("#search-input").catcomplete({
        delay: 0,
        source: rns,
        select: function (event, ui) {
            $('#tree').jstree(true).show_all();
            $('#tree').jstree('search', ui.item.value);
        }
    });

});
$(function () {
    CHARTDIALOG.dialog({
        position: {
            my: "left top",
            at: "right bottom",
            of: $('header')
        },
        autoOpen: false,
        dialogClass: "no-close",
        title: "Radionuclide decay chart",
        width: 510,
        height: 450,
        minHeight: 200,
        minWidth: 510,
    });
});



function formatBR(br) {
    if (br >= 0.1) {
        br = Math.round(br * 100).toString();
    } else if (br >= 0.005) {
        br = (Math.round(br * 1000) / 10).toString();
    } else {
        br = (br * 100).toExponential(1).replace(/e\-?/, '×10⁻').replace('⁻0', '⁻⁰').replace('⁻1', '⁻¹').replace('⁻2', '⁻²').replace('⁻3', '⁻³').replace('⁻4', '⁻⁴').replace('⁻5', '⁻⁵').replace('⁻6', '⁻⁶').replace('⁻7', '⁻⁷').replace('⁻8', '⁻⁸').replace('⁻9', '⁻⁹').replace('⁻10', '⁻¹⁰');
    }
    return br.concat("%");
}
function rotate(xy, degree) {
    let x = Math.cos(degree) * xy.x - Math.sin(degree) * xy.y;
    let y = Math.sin(degree) * xy.x + Math.cos(degree) * xy.y;
    return {
        x,
        y
    };
}
function getPosition(node) {
    var x = (xrn - (node.A - node.Z) * 100);
    var y = (yrn - node.Z * 100);
    if (node.state == "m") {
        x -= 200;
        y -= 200;
        if (node.name == "Pa-234m") {
            x += 200 + 200;
            y += 200 + 200;
        }
    } else if (node.state == "n") {
        x += 200;
        y += 200;
    }
    let degree = Math.PI / 4;
    var {
        x,
        y
    } = rotate({
        x,
        y
    }, degree);
    y = y / 2;
    if (node.name == "U-235m") {
        x += 150;
    }
    if (node.name == "Am-246m") {
        y += 141.5;
    }
    return {
        x,
        y
    };
}
function searchUnfocus(input) {
    input.value = "";
}
function getRn(rn) {
    const index = decaydata.findIndex(object => {
        return object.name === rn;
    });
    return decaydata[index];
}



function toggleMap() {
  var x = document.getElementById("map");
  var y = document.getElementById("tree");
  var z = document.getElementById("cy");
  if (x.style.visibility === "hidden") {
    x.style.visibility = "visible";
    y.style.visibility = "hidden";
    z.style.visibility = "hidden";
  } else {
    x.style.visibility = "hidden";
    y.style.visibility = "visible";
    z.style.visibility = "visible";
  }
}

                            


function createRect(x,y,z){
    return "<rect id='ID"+z+"' x='"+x+"' y='"+y+"' width='.90' height='.90' />";
}
function getPeriodicTable(Z){
   
   let svg = "<svg version='1.1' id='periodic_table' fill='#999999' xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' x='0px' y='0px' viewBox='.9 .9 18.1 9.5' style='enable-background:new .9 .9 18.1 9.5;' xml:space='preserve'>";
    svg = svg+"<style type='text/css'>";
    svg = svg+"#ID"+Z+" {";
    svg = svg+"fill: red;";
    svg = svg+"}";
    svg = svg+"</style>";
    //svg = svg+"<rect id='ID1' onclick='selectElement(1)'' x='1' y='1' width='.90' height='.90' />";
    svg = svg+createRect(1,1,1);
    svg = svg+createRect(18,1,2);
    svg = svg+createRect(1,2,3);
    svg = svg+createRect(2,2,4);
    for (let i = 13; i < 19; i++) {
    svg = svg+createRect(i,2,i-8);
    }
    svg = svg+createRect(1,3,11);
    svg = svg+createRect(2,3,12);
    for (let i = 13; i < 19; i++) {
    svg = svg+createRect(i,3,i);
    }
    for (let i = 1; i < 19; i++) {
    svg = svg+createRect(i,4,i+18);
    }
    for (let i = 1; i < 19; i++) {
    svg = svg+createRect(i,5,i+36);
    }
    svg = svg+createRect(1,6,55);
    svg = svg+createRect(2,6,56);
    for (let i = 4; i < 19; i++) {
    svg = svg+createRect(i,8.3,i+52);
    }
    for (let i = 4; i < 19; i++) {
    svg = svg+createRect(i,6,i+68);
    }
    svg = svg+createRect(1,7,87);
    svg = svg+createRect(2,7,88);
    for (let i = 4; i < 19; i++) {
    svg = svg+createRect(i,9.3,i+85);
    }
    for (let i = 4; i < 19; i++) {
    svg = svg+createRect(i,7,i+100);
    }
    svg = svg+"<line x1='2.9' y1='6' x2='4' y2='8.3' stroke='#999999' stroke-width='.2%' />";
    svg = svg+"<line x1='2.9' y1='7.9' x2='4' y2='10.1' stroke='#999999' stroke-width='.2%' />";
svg = svg+"</svg>";
    return svg;
}
