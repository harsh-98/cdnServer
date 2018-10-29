var http = require('http');
var https = require('https');
var request = require('request');
//var fs = require('fs');

http.createServer(function (req, res) {
//  res.write('Hello World!'); //write a response to the client
	var ip = (req.headers['x-forwarded-for'] || '').split(',')[0] || req.connection.remoteAddress;
	
	console.log(ip);
	
	request({url:"http://getcitydetails.geobytes.com/GetCityDetails?fqcn="+ip},function(error,res2,body){
	var data = JSON.parse(body);	
	
	console.log("Country of client is :: "+data['geobytescountry']);
		if(data['geobytescountry'] == "India")
			{res.writeHead(302,  {Location: "http://google.com"});
			res.end();		
			}  
		else	
			{res.writeHead(302,  {Location: "http://yahoo.com"});  
			res.end();			
			}	
	});
		
	
	
}).listen(80);
