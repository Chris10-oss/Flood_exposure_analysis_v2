#Flood Exposure Analysis version 5.3
#primary author: Robert Berstch
#secondary author: Christos Iliadis
#host: Newcastle University

#modules required for algorithm
import os
import rtree
import re
from shapely.geometry import shape, Point
import datetime
import pandas as pd
import geopandas as gpd
import warnings
from operator import itemgetter

#modules required for the interface
import ipywidgets as widgets
from IPython.display import display

folder_input = "Copy the folder path with the flood depth file or files"
bldgs_shp = "Copy the file path with the buildings shapefile"

cols_list = []
df1 = gpd.read_file(bldgs_shp)  
for n in df1.columns:
    cols_list.append(n)

shp_field = "UID" #select the building ID from the shapefile

#remember to check the buffer value
buffer_value = 150 #check the grid resolution

def process_data(ev):

    T_start = datetime.datetime.now()
    bldg_file = bldgs_shp
    input_folder = folder_input
    
    if not os.path.exists(os.path.dirname(input_folder) + '/Outputs_Events'):
        os.makedirs(os.path.dirname(input_folder) + '/Outputs_Events')

    #Creating the spatial index with the rtree module is only done for one depth file using X,Y only    
    print('...creating spatial index...')
    file_count = sorted([f for f in os.listdir(input_folder) if os.path.isfile(input_folder + '/' + f)])

    #first get the resolution of the grid:
    df_res = pd.read_csv(input_folder + '/' + file_count[0], nrows=3)
    xdiff = df_res.iloc[2,0] - df_res.iloc[1,0]
    ydiff = df_res.iloc[2,1] - df_res.iloc[1,1]
    if xdiff != 0:
        dx = xdiff
    elif xdiff == 0:
        dx = ydiff
    del(df_res)     
    buffer_distance = ((buffer_value)/100)*dx #in % of grid resolution #was 150 -> 100

    x=[]
    y=[]
    with open(input_folder + '/' + file_count[0], 'r') as t:
        aline = t.readline().strip()       
        aline = t.readline()
        while aline != '':
            column = re.split('\s|\s\s|\t|,',str(aline))
            x.append(float(column[0]))
            y.append(float(column[1]))
            aline = t.readline()    
    t.close()

    cell_idx=[]
    for idx, xi in enumerate(x): #generating a simple index based on the line number of the X coords 
        cell_idx.append(idx)

    index = rtree.index.Index() #creating the spatial index
    for pt_idx, xi, yi in zip(cell_idx,x,y):
        index.insert(pt_idx, (xi,yi))

    del(cell_idx)

    cell_index = [] #equal to line number of depth file to be read afterwards
    buffer_list = []
    bldgs = gpd.GeoDataFrame.from_file(bldg_file)
    bldgs_n = len(bldgs)
    bldgs_df = gpd.GeoDataFrame(bldgs[[str(shp_field), 'geometry']]) #the columns 'fid' and 'geometry' need to exist as header name
    del(bldgs)

    for b_id, b_geom in zip(bldgs_df[str(shp_field)], bldgs_df['geometry']):
        buffer = shape(b_geom.buffer(float(buffer_distance), resolution=10)) #create a buffer polygon for the building polygons from resolution 10 to 16
        for cell in list(index.intersection(buffer.bounds)): #first check if the point is within the bounding box of a building buffer
            cell_int = Point(x[cell], y[cell])  
            if cell_int.intersects(buffer): #then check if the point intersects with buffer polygon
                buffer_list.append(b_id) #store the building ID
                cell_index.append(cell)  #store the line inedex of the intersecting points

    df_b = pd.DataFrame(list(zip(buffer_list, cell_index)), columns=[str(shp_field),'cell']) 
    df_b = df_b.sort_values(by=['cell'])    
    print('spatial index created')

    #------------------------------------------------------------------------------reading depth files
    
    files = file_count

    for i, filename in enumerate(files):
        f=open(input_folder + '/' + filename)    
        print('processing file: ' + str(filename))  
        Z=[]
        aline = f.readline().strip()       
        aline = f.readline()
        while aline != '':
            column = re.split('\s|\s\s|\t|,',str(aline))
            Z.append(float(column[2]))
            aline = f.readline()
        f.close()              

        #--------------------------------------------------------------------------spatial intersection and classification
        #the next line reads the depth values from the file according to cell index from above and stores the depth with the intersecting building ID
        
        df = pd.DataFrame(list(zip(itemgetter(*cell_index)(Z),buffer_list)), columns=['depth',str(shp_field)]) 
        del(Z)

        #based on the building ID the mean and maximum depth are established and stored in a new data frame:
        mean_depth = pd.DataFrame(df.groupby([str(shp_field)])['depth'].mean().astype(float)).round(3).reset_index(level=0).rename(columns={'depth':'mean_depth'})  
        p90ile_depth = pd.DataFrame(df.groupby([str(shp_field)])['depth'].quantile(0.90).astype(float)).round(3).reset_index(level=0).rename(columns={'depth':'p90ile_depth'})
        categ_df = pd.merge(mean_depth, p90ile_depth)
        del(mean_depth, p90ile_depth)

        #classify the building according the threshold values
        categ_df['class'] = 'A) Low'
        categ_df['class'][(categ_df['mean_depth'] >= 0) & (categ_df['mean_depth'] < 0.10) & (categ_df['p90ile_depth'] < 0.30)] = 'A) Low'
        categ_df['class'][(categ_df['mean_depth'] >= 0) & (categ_df['mean_depth'] < 0.10) & (categ_df['p90ile_depth'] >= 0.30)] = 'B) Medium'
        categ_df['class'][(categ_df['mean_depth'] >= 0.10) & (categ_df['mean_depth'] < 0.30) & (categ_df['p90ile_depth'] < 0.30)] = 'B) Medium' 
        categ_df['class'][(categ_df['mean_depth'] >= 0.10) & (categ_df['p90ile_depth'] >= 0.30)] = 'C) High'                                                                                              
 
        #------------------------------------------------------------------------------merge results with a copy of the building layer and create output files
                
        bldgs_data = gpd.read_file(bldg_file)
        bldgs_df = gpd.GeoDataFrame(bldgs_data[[str(shp_field), 'geometry']])
        finalf = bldgs_df.merge(categ_df, on=str(shp_field), how='left') #the merging of the building shapefile and the categoty dataframe into the final file

        finalf['area'] = (finalf.area).astype(int) #calculate the area for each building
        finalf.to_file(os.path.dirname(input_folder) + '/Outputs_Events/' + str(filename.split('.')[0]) + '_floodrisk.shp')
        cat_low = (finalf['class'] == 'A) Low').sum()
        cat_medium = (finalf['class'] == 'B) Medium').sum()        
        cat_high = (finalf['class'] == 'C) High').sum()
        del(categ_df)

        del(finalf['geometry'])
        finalf_csv = pd.DataFrame(finalf)
        finalf_csv.to_csv(os.path.dirname(input_folder) + '/Outputs_Events/' + str(filename.split('.')[0]) + '_floodrisk.csv')

        del(bldgs_data,bldgs_df,finalf,finalf_csv,df)     

        with open(os.path.dirname(input_folder) + '/Outputs_Events/' + str(filename.split('.')[0]) + '_summary.txt', 'w') as sum_results:
            sum_results.write('Summary of Exposure Analysis for: ' + str(filename) + '\n\n'                    
                    + 'Input folder: ' + str(input_folder) + '\n'
                    + 'Building file: ' + str(bldg_file) + '\n\n'
                    + 'Number of depth files: ' + str(len(file_count)) + '\n'
                    + 'Number of buildings: ' + str(bldgs_n) + '\n'
                    + 'Grid resolution: ' + str(dx) +'m'+ '\n'
                    + 'Buffer distance: ' + str(buffer_value) +'% or ' +str(buffer_distance) +'m'+ '\n\n' 
                    + 'Low: ' + str(cat_low) + '\n'#
                    + 'Medium: ' +str(cat_medium) + '\n'
                    + 'High: ' +str(cat_high) + '\n\n')
            sum_results.close()

    del(x,y)  
    del(buffer_list,cell_index,df_b)         
    print('Finished. Time required: ' + str(datetime.datetime.now() - T_start)[:-4])

process_data('test')
